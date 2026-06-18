from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, ValidationError

from .config import settings
from .reverse_engineer.camt_parser import Camt053Parser
from .reverse_engineer.dataset_builder import DatasetBuilder
from .reverse_engineer.matcher import MatchingEngine
from .reverse_engineer.models import CamtTransaction, FlatLine, MatchingSignals, ScoringWeights
from .reverse_engineer_schemas import RegexSummary, ReconPatternRow, ReconPatternsResponse

logger = logging.getLogger(__name__)


class LlmPatternSpec(BaseModel):
    """
    Pattern specification returned by the LLM.

    The LLM must provide:
    - A STRICT regex that actually matches the flat-file lines end-to-end and
      is safe for parsing.
    - A (possibly looser) regex or pattern string and human-friendly summary
      for explanation in the UI.
    """

    delimiter_type: str  # "FIXED_WIDTH" or "DELIMITED" or "UNKNOWN"
    # Strict line-matching regex used for parsing; must contain id, amount, date.
    regex_pattern_strict: str
    # Optional additional / looser pattern (kept for backwards-compatibility / UI).
    regex_pattern: Optional[str] = None
    amount_factor: float
    date_format: str  # e.g. "YYYY-MM-DD", "YYYYMMDD"
    # Human-readable description of the flat-file structure.
    human_summary: Optional[str] = None


class LlmMatchedPair(BaseModel):
    """
    Minimal match record surfaced to the API consumer.
    """

    camt_transaction_id: str
    flat_line_number: int
    flat_raw_line: str
    pair_confidence: float
    matched_signals: List[str]
    # NEW: carry the raw MatchingSignals as a plain dict so it survives JSON round-trips
    raw_signals: Dict[str, Any] | None = None


class LlmReconcileResponse(BaseModel):
    """
    High-level response for LLM-driven reverse engineering.

    NOTE: This is intentionally simpler than the heuristic
    reverse_engineer_api.ReconcileResponse – it is focused on
    surfacing the learned pattern and the best CAMT↔flat matches
    used as training examples.
    """

    # Strict regex to be used for parsing / downstream pattern flows.
    regex_pattern_strict: str
    # Optional additional pattern (for backwards compatibility / display).
    regex_pattern: Optional[str]
    delimiter_type: str
    amount_factor: float
    date_format: str
    # Optional human-friendly summary of the layout.
    human_summary: Optional[str]
    samples: List[Dict[str, Any]]
    top_matches: List[LlmMatchedPair]
    raw_llm_spec: Dict[str, Any]
    confidence_score: float
    confidence_explanation: str


class LlmReverseEngineerService:
    """
    New LLM-backed reverse engineering service that:

    1. Parses CAMT.053 XML into rich CamtTransaction objects.
    2. Scans an unknown flat file line-by-line.
    3. Uses a heuristic MatchingEngine to produce high-confidence
       CAMT↔flat-line candidate pairs.
    4. Builds a dataset of examples for the LLM (CAMT+flat+pair_confidence).
    5. Asks the LLM to infer a regex pattern and related metadata.
    6. Returns the learned pattern together with the examples and
       top matches, suitable for downstream UI and LLM refinement.
    """

    def __init__(
        self,
        max_sample: int = 100,
        min_pair_confidence: float = 0.7,
        top_n_per_tx: int = 3,
    ) -> None:
        self.max_sample = max_sample
        self.min_pair_confidence = min_pair_confidence
        self.top_n_per_tx = top_n_per_tx

        weights = ScoringWeights(
            w_exact_reference=3.0,
            w_end_to_end=2.0,
            w_acct_svcr_ref=2.0,
            w_uetr=2.0,
            w_invoice_ref=2.5,
            w_amount=3.0,
            w_date=2.0,
            w_counterparty=2.0,
            w_ustrd_overlap=1.5,
        )
        self.match_engine = MatchingEngine(scoring_weights=weights)
        self.dataset_builder = DatasetBuilder(engine=self.match_engine)

    # ------------------------------------------------------------------
    # CAMT + flat-file ingestion helpers
    # ------------------------------------------------------------------

    def _parse_camt_from_bytes(self, xml_bytes: bytes) -> List[CamtTransaction]:
        """
        Parse CAMT.053 XML from bytes into CamtTransaction objects.

        We write to a temporary file to reuse Camt053Parser which expects
        a Path; this keeps the parser simple and testable.
        """
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            tmp.write(xml_bytes)
            tmp_path = Path(tmp.name)

        try:
            parser = Camt053Parser(tmp_path)
            txs = parser.parse_transactions()
        finally:
            try:
                tmp_path.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                logger.warning("Failed to delete temporary CAMT file %s", tmp_path)

        """if len(txs) > self.max_sample:
            txs = txs[: self.max_sample]"""

        return txs

    @staticmethod
    def _flat_lines_from_bytes(flat_bytes: bytes) -> List[FlatLine]:
        text = flat_bytes.decode("utf-8", errors="replace")
        lines: List[FlatLine] = []
        for idx, raw in enumerate(text.splitlines(), start=1):
            if not raw.strip():
                continue
            lines.append(FlatLine(line_number=idx, raw=raw))
        return lines

    def _build_llm_examples(
        self,
        camt_txs: List[CamtTransaction],
        flat_lines: List[FlatLine],
    ) -> Dict[str, Any]:
        """
        Use MatchingEngine + DatasetBuilder to produce LLM-ready examples.

        Returns a dict:
        {
          "samples": [
             {
               "camt": {...},
               "flat_raw_line": "...",
               "pair_confidence": 0.98,
               "pair_components": [...],
               "pair_explanation": "..."
             },
             ...
          ],
          "top_matches": [ ... simplified match view ... ]
        }
        """
        dataset = self.dataset_builder.build_dataset(
            transactions=camt_txs,
            flat_lines=flat_lines,
            min_confidence=self.min_pair_confidence,
            top_n_per_tx=self.top_n_per_tx,
        )
        dataset_dict = dataset.to_dict()

        # Track PSR line numbers that are used as LLM training samples,
        # so we can avoid reusing them in the "top matches per transaction" view.
        training_line_numbers: set[int] = set()

        # Ensure all samples are JSON-serializable primitives.
        # Dataset.to_dict() already converts dataclasses to dicts, but we
        # defensively normalise the new fields as well.
        normalised_samples: List[Dict[str, Any]] = []
        for s in dataset_dict.get("samples", []):
            comps: List[Dict[str, Any]] = []
            # Keep track of which flat-file line numbers are used for LLM training.
            try:
                ln = int(s.get("flat_line_number") or 0)
                if ln > 0:
                    training_line_numbers.add(ln)
            except (TypeError, ValueError):
                pass

            raw_components = s.get("pair_components", []) or []
            for c in raw_components:
                # c can be either a PairComponentEvidence instance or an already-serialised dict
                if hasattr(c, "component"):
                    raw_psr = getattr(c, "raw_value_psr", None)
                    # DO NOT pass raw CAMT/XML blobs to the LLM – keep this None in the prompt payload.
                    raw_camt = getattr(c, "raw_value_camt", None)
                    comps.append(
                        {
                            "component": getattr(c, "component", None),
                            "weight": float(getattr(c, "weight", 0.0) or 0.0),
                            "passed": bool(getattr(c, "passed", False)),
                            "evidence": getattr(c, "evidence", None),
                            "raw_value_psr": raw_psr,
                            # Intentionally drop raw_value_camt from the LLM-facing JSON
                            # to avoid sending large XML/text blobs.
                            "raw_value_camt": None,
                        }
                    )
                else:
                    # assume dict-like
                    raw_psr = c.get("raw_value_psr")
                    raw_camt = c.get("raw_value_camt")
                    comps.append(
                        {
                            "component": c.get("component"),
                            "weight": float(c.get("weight", 0.0)),
                            "passed": bool(c.get("passed", False)),
                            "evidence": c.get("evidence"),
                            "raw_value_psr": raw_psr,
                            # Same rationale: drop raw CAMT content for the LLM payload.
                            "raw_value_camt": None,
                        }
                    )
            s["pair_components"] = comps
            # pair_explanation is already a string/None from DatasetBuilder
            normalised_samples.append(s)

        dataset_dict["samples"] = normalised_samples

        # Build a flattened top_matches view: for each CAMT tx, take the single
        # best pair_confidence (if any), excluding PSR lines already used
        # as LLM training samples.
        matches_by_tx = self.match_engine.match_all(
            transactions=camt_txs,
            flat_lines=flat_lines,
            top_n_per_tx=1,
        )

        top_matches: List[LlmMatchedPair] = []
        for tx in camt_txs:
            tx_id = tx.primary_id()
            pairs = matches_by_tx.get(tx_id) or []
            if not pairs:
                continue
            ps = pairs[0]
            if ps.pair_confidence < self.min_pair_confidence:
                continue

            # Do not reuse PSR lines that were already selected as LLM training samples.
            if ps.flat_line.line_number in training_line_numbers:
                continue

            matched_signals: List[str] = []
            sig_obj = ps.matched_signals
            # Normalise signals to a plain dict so it can be JSON-serialised and
            # later rehydrated into MatchingSignals by Pydantic inside LlmMatchedPair.
            if sig_obj is None:
                sig_dict: Dict[str, Any] | None = None
            elif hasattr(sig_obj, "dict"):
                sig_dict = sig_obj.dict()
            elif hasattr(sig_obj, "model_dump"):
                sig_dict = sig_obj.model_dump()
            else:
                sig_dict = vars(sig_obj)

            # For local use in this function keep the rich object (if present)
            sig = sig_obj or MatchingSignals()
            if sig.end_to_end_match:
                matched_signals.append("end_to_end_id")
            if sig.acct_svcr_ref_match:
                matched_signals.append("acct_svcr_ref")
            if sig.uetr_match:
                matched_signals.append("uetr")
            if sig.exact_reference_matches:
                matched_signals.append("exact_reference")
            if sig.invoice_ref_matches:
                matched_signals.append("invoice_ref")
            if sig.amount_match and sig.amount_match.matched:
                matched_signals.append("amount")
            if sig.date_match and sig.date_match.matched:
                matched_signals.append("date")
            if sig.counterparty_match_score > 0.0:
                matched_signals.append("counterparty")
            if sig.ustrd_token_overlap > 0.0:
                matched_signals.append("ustrd_tokens")

            top_matches.append(
                LlmMatchedPair(
                    camt_transaction_id=tx_id,
                    flat_line_number=ps.flat_line.line_number,
                    flat_raw_line=ps.flat_line.raw,
                    pair_confidence=ps.pair_confidence,
                    matched_signals=matched_signals,
                    raw_signals=sig_dict,
                )
            )

        return {
            "samples": dataset_dict["samples"],
            "top_matches": [m.model_dump() for m in top_matches],
        }

    # ------------------------------------------------------------------
    # LLM integration
    # ------------------------------------------------------------------

    @staticmethod
    def _call_llm(prompt_json: str, samples: List[Dict[str, Any]]) -> LlmPatternSpec:
        """
        Call external LLM via OpenRouter using an OpenAI-compatible API.

        This function is model-agnostic: it only expects the LLM to return
        a JSON object matching LlmPatternSpec.
        """
        from .config import settings

        provider = "anthropic"
        model    = settings.llm_model
        max_tok  = settings.llm_max_tokens

        #provider = getattr(settings, "llm_provider", None) or os.getenv("LLM_PROVIDER", "openai").lower()
        api_key = os.getenv("OPENROUTER_API_KEY", "")

        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.warning("ANTHROPIC_API_KEY not set — Tier 2c LLM adjudication skipped.")
                return []
            import httpx
            import anthropic

            # VERY UNSAFE: disables TLS verification
            _insecure_httpx_client = httpx.Client(verify=False)

            _anthropic_client = anthropic.Anthropic(
                api_key=api_key,
                http_client=_insecure_httpx_client,
            )
            
            ##_anthropic_client = _anthropic.Anthropic(api_key=api_key)
            _openai_client = None
        elif provider != "openai":
            raise RuntimeError("Only 'openai' provider is currently supported for reverse-engineer LLM flow")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for LLM reverse-engineer")


        if provider == "anthropic":
            system_prompt = r"""You reverse-engineer financial flat files using paired CAMT.053 XML data, a `flat_raw_line`, and match heuristics.
        Output EXACTLY one JSON object to generate a strict Python regex matching `flat_raw_line` from ^ to $.

        CRITICAL RULES:
        1. IGNORE HEURISTICS: They incorrectly merge fields. Compare clean `camt` values to `flat_raw_line` to find the true left-to-right sequence.
        2. SPACE-BLINDNESS: NEVER use exact character counts (e.g., `.{30}`, `\s{17}`) for space-padded text fields. Always use flexible quantifiers (`.+?`, `\s+`, `\S+`).
        3. STRICT ANCHORS: You MUST count and use exact lengths for continuous, non-padded numbers/IDs (e.g., `(?P<id>.{12})`, `(?P<date>\d{8})`, `(?P<amount>\d{12})`).
        4. CR/DR INDICATOR: If "CR" or "DR" immediately follows the amount, isolate it: `(?P<indicator>CR|DR)`. Do NOT merge it into the adjacent reference (e.g., "CRINV" -> "CR" + "INV").

        JSON FORMAT REQUIRED:
        {
        "delimiter_type": "FIXED_WIDTH" | "DELIMITED" | "UNKNOWN",
        "field_mapping": "Left-to-right breakdown. Note literal strings, state exact lengths for strict fields, and note CR/DR presence.",
        "regex_pattern_strict": "Regex from ^ to $. MUST interleave strict anchors (e.g., \d{12}) and flexible spacing (\s+, .+?).",
        "regex_pattern": null,
        "amount_factor": float, // e.g. 0.01 if 2500 means 25.00
        "date_format": "YYYYMMDD",
        "human_summary": "Brief layout description"
        }
        No prose, Markdown, or commentary outside the JSON."""

                
            response = _anthropic_client.messages.create(
                model=model,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt_json}],
                temperature=0,
                max_tokens=max_tok,
            )
            raw_content = response.content[0].text
            content = json.loads(raw_content)
        else:
            url = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1/chat/completions")
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You output only JSON. No prose."},
                    {"role": "user", "content": prompt_json},
                ],
                "temperature": 0.0,
                "max_tokens": 1024,  
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            start = time.perf_counter()
            resp = requests.post(url, headers=headers, json=payload, timeout=60, verify=False)
            duration = (time.perf_counter() - start) * 1000
            logger.info("LLM reverse-engineer call completed in %.0fms", duration)

            if resp.status_code != 200:
                logger.error("LLM API error: %s %s", resp.status_code, resp.text[:500])
                raise RuntimeError(f"LLM API error: {resp.status_code}")

            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception as exc:
                raise RuntimeError("Unexpected LLM response format") from exc

        try:
            raw_obj = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("LLM did not return valid JSON: %s", content[:500])
            raise RuntimeError("LLM did not return valid JSON") from exc

        try:
            spec = LlmPatternSpec.model_validate(raw_obj)
        except ValidationError as exc:
            logger.error("LLM JSON did not match LlmPatternSpec: %s", exc)
            raise RuntimeError("LLM JSON did not match expected schema") from exc

        # Basic sanity check: ensure named groups exist for id/amount/date on the strict regex
        strict = spec.regex_pattern_strict
        if not re.search(r"\(\?P<id>", strict) or not re.search(
            r"\(\?P<amount>", strict
        ) or not re.search(r"\(\?P<date>", strict):
            logger.warning(
                "LLM regex_pattern_strict may not contain required named groups id/amount/date: %s",
                strict,
            )

        return spec

    def _build_llm_prompt(self, samples: List[Dict[str, Any]]) -> str:
        """
        Build a JSON-only prompt for the LLM, containing:

        - High-confidence CAMT↔flat-line pairs with pair_confidence
        - Instructions to infer a regex pattern and parsing metadata
        """
        system_instructionsbkp =  r"""You are a reverse-engineering assistant for financial flat files.
You are given paired examples from a CAMT.053 XML and an unknown flat file.
Each sample contains:
- camt: normalized CAMT transaction with references, remittance, counterparties
- flat_raw_line: the corresponding flat-file line
- pair_components: heuristic approximations of matches.

From these examples, you MUST infer a single strict regex pattern that can parse
the flat file structure and actually match the provided flat_raw_line examples
from start (^) to end ($).

CRITICAL RULES:
1. IGNORE HEURISTIC BOUNDARIES: The heuristics might merge fields together. Trust your own eyes. Look at the clean `camt` values, find where they live in the `flat_raw_line`, and determine the true left-to-right sequence.
2. THE "SPACE-BLINDNESS" RULE (CRUCIAL): LLMs cannot accurately count whitespace characters because multiple spaces are compressed into single tokens. 
   - DO NOT attempt to use exact counts (like `.{30}` or `\s{17}`) for fields padded with spaces. You will guess wrong and break the regex.
   - INSTEAD, use flexible space absorbers (like `\s+`, `.+?`, or `\S+`) for the space-padded text fields (e.g., Remittance, Invoice, Counterparty).
3. STRICT ANCHORS FOR NUMBERS/IDs: You CAN and MUST count exact lengths for continuous, non-space fields. These act as your unbreakable anchors.
   - E.g., An ID like "TX-2027-0001" is exactly 12 characters: `(?P<id>.{12})`
   - E.g., A Date like "20260610" is exactly 8 digits: `(?P<date>\d{8})`
   - E.g., A padded Amount like "000000002500" is exactly 12 digits: `(?P<amount>\d{12})`
4. CREDIT/DEBIT INDICATOR: Financial files often place a "CR" (Credit) or "DR" (Debit) immediately adjacent to the amount. Look closely at the raw string! If you see "CR" or "DR" right after the amount, you MUST extract it using its own group: `(?P<indicator>CR|DR)`. Do NOT accidentally merge "CR" into the invoice reference (e.g., "CRINV..." is usually "CR" + "INV...").
5. COMBINING THEM: Your final regex should interleave strict lengths with flexible spacing. Example logic: `(?P<id>.{12})(?P<date>\d{8})(?P<remittance>.+?)(?P<amount>\d{12})(?P<indicator>CR|DR)?(?P<invoice_ref>\S+)\s+(?P<counterparty>.*)$`

You MUST respond with EXACTLY one JSON object with these keys:
  - delimiter_type: "FIXED_WIDTH", "DELIMITED", or "UNKNOWN"
  - field_mapping: "Left-to-right breakdown of the raw line. State the literal string found for each field. Explicitly state which fields are 'Strict (exact count)' and which are 'Space-padded'. Clearly identify if a CR/DR indicator is present."
  - regex_pattern_strict: "A single-line Python regex from ^ to $. MUST use exact widths (e.g. \d{12}) for numbers/IDs, and flexible spacing (\s+, .+?) for padded text. Must include (?P<indicator>CR|DR) if found."
  - regex_pattern: another regex string, or null
  - amount_factor: a float
  - date_format: "a string like 'YYYY-MM-DD' or 'YYYYMMDD'"
  - human_summary: "a short plain-text description"
No prose, no Markdown, no commentary outside this JSON object."""


        system_instructions = r"""You reverse-engineer financial flat files using paired CAMT.053 XML data, a `flat_raw_line`, and match heuristics.
        Output EXACTLY one JSON object to generate a strict Python regex matching `flat_raw_line` from ^ to $.

        CRITICAL RULES:
        1. IGNORE HEURISTICS: They incorrectly merge fields. Compare clean `camt` values to `flat_raw_line` to find the true left-to-right sequence.
        2. SPACE-BLINDNESS: NEVER use exact character counts (e.g., `.{30}`, `\s{17}`) for space-padded text fields. Always use flexible quantifiers (`.+?`, `\s+`, `\S+`).
        3. STRICT ANCHORS: You MUST count and use exact lengths for continuous, non-padded numbers/IDs (e.g., `(?P<id>.{12})`, `(?P<date>\d{8})`, `(?P<amount>\d{12})`).
        4. CR/DR INDICATOR: If "CR" or "DR" immediately follows the amount, isolate it: `(?P<indicator>CR|DR)`. Do NOT merge it into the adjacent reference (e.g., "CRINV" -> "CR" + "INV").

        JSON FORMAT REQUIRED:
        {
        "delimiter_type": "FIXED_WIDTH" | "DELIMITED" | "UNKNOWN",
        "field_mapping": "Left-to-right breakdown. Note literal strings, state exact lengths for strict fields, and note CR/DR presence.",
        "regex_pattern_strict": "Regex from ^ to $. MUST interleave strict anchors (e.g., \d{12}) and flexible spacing (\s+, .+?).",
        "regex_pattern": null,
        "amount_factor": float, // e.g. 0.01 if 2500 means 25.00
        "date_format": "YYYYMMDD",
        "human_summary": "Brief layout description"
        }
        No prose, Markdown, or commentary outside the JSON."""

        prompt = {
            "instructions": system_instructions,
            "samples": samples,
           
        }
        return json.dumps(prompt)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_with_llm(self, camt_xml_bytes: bytes, flat_bytes: bytes) -> LlmReconcileResponse:
        """
        Full LLM reverse-engineering pipeline:

        1. Parse CAMT.053 into CamtTransaction objects.
        2. Convert flat bytes into FlatLine list.
        3. Use heuristic matching to produce high-confidence CAMT↔flat pairs.
        4. Feed these pairs into an LLM to infer a regex pattern and metadata.
        5. Return the learned pattern + the examples and top matches.
        """
        camt_txs_all = self._parse_camt_from_bytes(camt_xml_bytes)
        if not camt_txs_all:
            raise ValueError("No CAMT transactions found for LLM reverse-engineering")

        # Limit CAMT sample size only for the LLM regex-identification flow.
        camt_txs = camt_txs_all[: self.max_sample]

        flat_lines = self._flat_lines_from_bytes(flat_bytes)
        if not flat_lines:
            raise ValueError("Flat file is empty or whitespace only")

        llm_examples = self._build_llm_examples(camt_txs, flat_lines)
        samples = llm_examples["samples"]
        top_matches_raw = llm_examples["top_matches"]

        if not samples:
            raise ValueError(
                "No sufficiently high-confidence CAMT↔flat pairs found to drive LLM reverse-engineering"
            )

        prompt_json = self._build_llm_prompt(samples)
        
        pattern_spec = self._call_llm(prompt_json, samples)

        # Convert raw top_matches back into Pydantic models
        top_matches: List[LlmMatchedPair] = []
        for item in top_matches_raw:
            try:
                top_matches.append(LlmMatchedPair.model_validate(item))
            except ValidationError:
                continue

        # Inline confidence aggregation used to compute the backend score
        pair_confs: List[float] = []
        for s in samples:
            try:
                pc = float(s.get("pair_confidence", 0.0))
            except (TypeError, ValueError):
                pc = 0.0
            pair_confs.append(pc)

        if pair_confs:
            avg_pair_conf = sum(pair_confs) / len(pair_confs)
            strong_pairs = [pc for pc in pair_confs if pc >= 0.75]
            coverage = len(strong_pairs) / len(pair_confs) if pair_confs else 0.0
            confidence_score = 0.5 * avg_pair_conf + 0.5 * coverage
            confidence_score = max(0.0, min(1.0, confidence_score))
            explanation_parts = [
                f"{len(samples)} CAMT ↔ flat-file training samples used.",
                f"Average pair confidence across samples: {avg_pair_conf:.2f}.",
                f"High-confidence coverage (≥ 0.75): {coverage * 100:.1f}% of samples.",
            ]
            if top_matches:
                explanation_parts.append(
                    f"{len(top_matches)} top matches surfaced for inspection in the UI."
                )
            confidence_explanation = " ".join(explanation_parts)
        else:
            confidence_score = 0.0
            confidence_explanation = (
                "No CAMT ↔ flat-file training samples were available, so confidence is 0."
            )

        return LlmReconcileResponse(
            regex_pattern_strict=pattern_spec.regex_pattern_strict,
            regex_pattern=pattern_spec.regex_pattern,
            delimiter_type=pattern_spec.delimiter_type,
            amount_factor=pattern_spec.amount_factor,
            date_format=pattern_spec.date_format,
            human_summary=pattern_spec.human_summary,
            samples=samples,
            top_matches=top_matches,
            raw_llm_spec=pattern_spec.model_dump(),
            confidence_score=confidence_score,
            confidence_explanation=confidence_explanation,
        )

    @staticmethod
    def _infer_pattern_category(pattern_subtype: str | None) -> str:
        """
        Map backend recon pattern subtypes to high-level Pattern Category buckets.

        Categories:
        - Exact Match
        - Composite Key
        - Amount Tolerance
        - Fuzzy / NLP
        - Other
        """
        st = (pattern_subtype or "").upper()

        if "END_TO_END" in st or "EXACT" in st:
            return "Exact Match"
        if (
            "PMT_REF" in st
            or "INVOICE" in st
            or "COMPOSITE" in st
            or "COUNTERPARTY" in st
        ):
            return "Composite Key"
        if "VARIANCE" in st or "TOLERANCE" in st:
            return "Amount Tolerance"
        if (
            "TIER2B" in st
            or "TIER2C" in st
            or "FUZZY" in st
            or "AI" in st
            or "NLP" in st
        ):
            return "Fuzzy / NLP"
        return "Other"

    def analyze_recon_patterns(
        self,
        camt_xml_bytes: bytes,
        flat_bytes: bytes,
        regex_pattern: str | None = None,
    ) -> ReconPatternsResponse:
        """
        Aggregate CAMT↔PSR matches into reconciliation pattern buckets aligned to
        the Master Level taxonomy.

        If regex_pattern is provided, use it directly and do NOT call the LLM.
        Otherwise, fall back to the full LLM reverse-engineer pipeline.
        """
        # Always build matcher-derived examples up front, using the full CAMT set
        camt_txs = self._parse_camt_from_bytes(camt_xml_bytes)
        if not camt_txs:
            raise ValueError("No CAMT transactions found for recon pattern aggregation")

        flat_lines = self._flat_lines_from_bytes(flat_bytes)
        if not flat_lines:
            raise ValueError("Flat file is empty or whitespace only")

        llm_examples = self._build_llm_examples(camt_txs, flat_lines)
        samples = llm_examples["samples"]
        top_matches_raw = llm_examples["top_matches"]

        if regex_pattern is None:
            # For recon pattern aggregation, a regex is mandatory and must be supplied
            # by the caller (API route). We no longer call the LLM here.
            raise ValueError("regex_pattern is required for recon pattern aggregation")
        else:
            effective_regex = regex_pattern
            # Basic neutral defaults; these can be refined later if needed
            delimiter_type = "UNKNOWN"
            amount_factor = 1.0
            date_format = "UNKNOWN"

            top_matches_models: List[LlmMatchedPair] = []
            for item in top_matches_raw:
                try:
                    top_matches_models.append(LlmMatchedPair.model_validate(item))
                except ValidationError:
                    continue
            samples_for_summary = samples

        regex_summary = RegexSummary(
            regex_pattern=effective_regex,
            delimiter_type=delimiter_type,
            amount_factor=amount_factor,
            date_format=date_format,
            samples=samples_for_summary,
            top_matches=[m.model_dump() for m in top_matches_models],
        )

        # ------------------------------------------------------------------
        # Bucket top_matches into recon pattern rows
        # ------------------------------------------------------------------
        # - MASTER_LEVEL_1 / <REF_TAG>_EXACT (Exact Match category) when exact reference present
        #   one row per ref-tag subtype
        # - MASTER_LEVEL_2 / COMPOSITE_KEY (Composite Key category) otherwise
        level1_buckets: Dict[str, Dict[str, Any]] = {}
        level2_buckets: Dict[str, Dict[str, Any]] = {}

        # Helper to convert a CAMT reference field name into an *_EXACT subtype.
        # e.g. "EndToEndId" -> "END_TO_END_ID_EXACT"
        def _field_to_exact_subtype(field_name: str) -> str:
            snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", field_name).upper()
            return f"{snake}_EXACT"

        # Iterate over top matches and populate buckets
        for m in top_matches_models:
            camt_id = m.camt_transaction_id
            psr_id = str(m.flat_line_number)

            # Use exact_ref_matches_by_field as the sole source of "exact-ref-driven" tags.
            # This makes the pattern rules fully data-driven off whatever reference fields
            # the matcher actually found in the CAMT data (including other_refs).
            raw_sig_dict: Dict[str, Any] | None = getattr(m, "raw_signals", None)
            field_map: Dict[str, List[str]] = {}
            if raw_sig_dict and isinstance(raw_sig_dict, dict):
                # exact_ref_matches_by_field is stored as a dict[field_name -> [values]]
                raw_field_map = raw_sig_dict.get("exact_ref_matches_by_field") or {}
                if isinstance(raw_field_map, dict):
                    # keep only list-like values
                    for k, v in raw_field_map.items():
                        if isinstance(v, list):
                            field_map[k] = v

            if field_map:
                # For now, attribute this pair to the first field name (sorted) for
                # determinism. If you want one pattern row per field per pair, you
                # could loop over field_map.keys() here instead.
                ref_field_name = sorted(field_map.keys())[0]

                subtype = _field_to_exact_subtype(ref_field_name)
                ref_label = ref_field_name

                bucket = level1_buckets.setdefault(
                    subtype,
                    {
                        "pattern_level": "MASTER_LEVEL_1",
                        "pattern_subtype": subtype,
                        "pattern_category": LlmReverseEngineerService._infer_pattern_category(subtype),
                        "description": (
                            f"1:1 deterministic matches driven by exact structured "
                            f"reference on {ref_label}."
                        ),
                        "case_count": 0,
                        "bank_sum": 0.0,
                        "internal_sum": 0.0,
                        "example_psr_ids": [],
                        "example_camt_ids": [],
                    },
                )
                bucket["case_count"] += 1
                if len(bucket["example_psr_ids"]) < 5:
                    bucket["example_psr_ids"].append(psr_id)
                if len(bucket["example_camt_ids"]) < 5:
                    bucket["example_camt_ids"].append(camt_id)
            else:
                # MASTER_LEVEL_2 — composite key style. In this first cut we key buckets
                # by CAMT transaction id as a proxy for "amount/date/counterparty cluster".
                key = camt_id or "UNKNOWN"
                bucket = level2_buckets.setdefault(
                    key,
                    {
                        "pattern_level": "MASTER_LEVEL_2",
                        "pattern_subtype": "COMPOSITE_KEY",
                        "pattern_category": LlmReverseEngineerService._infer_pattern_category("COMPOSITE_KEY"),
                        "description": (
                            "Probabilistic composite-key matches driven by amount/date/"
                            "counterparty signals rather than exact references."
                        ),
                        "case_count": 0,
                        "bank_sum": 0.0,
                        "internal_sum": 0.0,
                        "example_psr_ids": [],
                        "example_camt_ids": [],
                    },
                )
                bucket["case_count"] += 1
                if len(bucket["example_psr_ids"]) < 5:
                    bucket["example_psr_ids"].append(psr_id)
                if len(bucket["example_camt_ids"]) < 5:
                    bucket["example_camt_ids"].append(camt_id)

        recon_rows: List[ReconPatternRow] = []

        # One MASTER_LEVEL_1 row per exact-ref subtype
        for bucket in level1_buckets.values():
            if bucket["case_count"] > 0:
                recon_rows.append(ReconPatternRow(**bucket))

        # Composite-key rows
        for bucket in level2_buckets.values():
            recon_rows.append(ReconPatternRow(**bucket))

        return ReconPatternsResponse(regex_summary=regex_summary, recon_patterns=recon_rows)
