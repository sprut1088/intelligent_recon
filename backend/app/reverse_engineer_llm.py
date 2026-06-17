from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import requests
from pydantic import BaseModel, ValidationError

from .config import settings
from .reverse_engineer.camt_parser import Camt053Parser
from .reverse_engineer.dataset_builder import DatasetBuilder
from .reverse_engineer.matcher import MatchingEngine
from .reverse_engineer.models import CamtTransaction, FlatLine, ScoringWeights

logger = logging.getLogger(__name__)


class LlmPatternSpec(BaseModel):
    """
    Pattern specification returned by the LLM.

    This is intentionally minimal: the LLM should decide how to parse the
    flat file, but we enforce the presence of some core fields.
    """

    delimiter_type: str  # "FIXED_WIDTH" or "DELIMITED" or "UNKNOWN"
    regex_pattern: str   # must contain at least id, amount, date groups
    amount_factor: float
    date_format: str     # e.g. "YYYY-MM-DD", "YYYYMMDD"


class LlmMatchedPair(BaseModel):
    """
    Minimal match record surfaced to the API consumer.
    """

    camt_transaction_id: str
    flat_line_number: int
    flat_raw_line: str
    pair_confidence: float
    matched_signals: List[str]


class LlmReconcileResponse(BaseModel):
    """
    High-level response for LLM-driven reverse engineering.

    NOTE: This is intentionally simpler than the heuristic
    reverse_engineer_api.ReconcileResponse – it is focused on
    surfacing the learned pattern and the best CAMT↔flat matches
    used as training examples.
    """

    regex_pattern: str
    delimiter_type: str
    amount_factor: float
    date_format: str
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
        max_sample: int = 50,
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

        if len(txs) > self.max_sample:
            txs = txs[: self.max_sample]

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

        # Ensure all samples are JSON-serializable primitives.
        # Dataset.to_dict() already converts dataclasses to dicts, but we
        # defensively normalise the new fields as well.
        normalised_samples: List[Dict[str, Any]] = []
        for s in dataset_dict.get("samples", []):
            comps: List[Dict[str, Any]] = []
            raw_components = s.get("pair_components", []) or []
            for c in raw_components:
                # c can be either a PairComponentEvidence instance or an already-serialised dict
                if hasattr(c, "component"):
                    comps.append(
                        {
                            "component": getattr(c, "component", None),
                            "weight": float(getattr(c, "weight", 0.0) or 0.0),
                            "passed": bool(getattr(c, "passed", False)),
                            "evidence": getattr(c, "evidence", None),
                            "raw_value_psr": getattr(c, "raw_value_psr", None),
                            "raw_value_camt": getattr(c, "raw_value_camt", None),
                        }
                    )
                else:
                    # assume dict-like
                    comps.append(
                        {
                            "component": c.get("component"),
                            "weight": float(c.get("weight", 0.0)),
                            "passed": bool(c.get("passed", False)),
                            "evidence": c.get("evidence"),
                            "raw_value_psr": c.get("raw_value_psr"),
                            "raw_value_camt": c.get("raw_value_camt"),
                        }
                    )
            s["pair_components"] = comps
            # pair_explanation is already a string/None from DatasetBuilder
            normalised_samples.append(s)

        dataset_dict["samples"] = normalised_samples

        # Build a flattened top_matches view: for each CAMT tx, take the single
        # best pair_confidence (if any).
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

            matched_signals: List[str] = []
            sig = ps.matched_signals
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
    def _call_llm(prompt_json: str) -> LlmPatternSpec:
        """
        Call external LLM via OpenRouter using an OpenAI-compatible API.

        This function is model-agnostic: it only expects the LLM to return
        a JSON object matching LlmPatternSpec.
        """
        provider = getattr(settings, "llm_provider", None) or os.getenv("LLM_PROVIDER", "openai").lower()
        api_key = os.getenv("OPENROUTER_API_KEY", "")

        if provider != "openai":
            raise RuntimeError("Only 'openai' provider is currently supported for reverse-engineer LLM flow")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for LLM reverse-engineer")

        url = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1/chat/completions")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You output only JSON. No prose."},
                {"role": "user", "content": prompt_json},
            ],
            "temperature": 0.0,
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

        # Basic sanity check: ensure named groups exist for id/amount/date
        if not re.search(r"\(\?P<id>", spec.regex_pattern) or not re.search(
            r"\(\?P<amount>", spec.regex_pattern
        ) or not re.search(r"\(\?P<date>", spec.regex_pattern):
            logger.warning(
                "LLM regex_pattern may not contain required named groups id/amount/date: %s",
                spec.regex_pattern,
            )

        return spec

    def _build_llm_prompt(self, samples: List[Dict[str, Any]]) -> str:
        """
        Build a JSON-only prompt for the LLM, containing:

        - High-confidence CAMT↔flat-line pairs with pair_confidence
        - Instructions to infer a regex pattern and parsing metadata
        """
        system_instructions = (
            "You are a reverse-engineering assistant for financial flat files.\n"
            "You are given paired examples from a CAMT.053 XML and an unknown flat file.\n"
            "Each sample contains:\n"
            "- camt: normalized CAMT transaction with references, remittance, counterparties\n"
            "- flat_raw_line: the corresponding flat-file line\n"
            "- pair_confidence: your heuristic system's confidence that they represent\n"
            "  the same underlying transaction.\n\n"
            "From these examples, you MUST infer a single regex pattern that can parse\n"
            "the flat file structure.\n\n"
            "Your task:\n"
            "1. Decide if the flat file is delimited (fields separated by a character)\n"
            "   or fixed width, or unknown.\n"
            "2. Infer a regex pattern with at least three named capture groups:\n"
            "   (?P<id>...), (?P<amount>...), (?P<date>...). You MAY add more named\n"
            "   groups (e.g. (?P<bank_ref>...), (?P<counterparty>...)).\n"
            "3. Decide an amount_factor (float) such that parsed numeric values * amount_factor\n"
            "   equal the actual decimal amount from CAMT.\n"
            "4. Decide a date_format string describing the flat-file date layout, for example:\n"
            "   - 'YYYY-MM-DD'\n"
            "   - 'YYYYMMDD'\n\n"
            "You MUST respond with EXACTLY one JSON object with these keys:\n"
            "  - delimiter_type: 'FIXED_WIDTH', 'DELIMITED', or 'UNKNOWN'\n"
            "  - regex_pattern: a single-line Python regex string with named groups\n"
            "                   at least id, amount, date\n"
            "  - amount_factor: a float\n"
            "  - date_format: a string like 'YYYY-MM-DD' or 'YYYYMMDD'\n"
            "No prose, no Markdown, no commentary. JSON only."
        )
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
        camt_txs = self._parse_camt_from_bytes(camt_xml_bytes)
        if not camt_txs:
            raise ValueError("No CAMT transactions found for LLM reverse-engineering")

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
        pattern_spec = self._call_llm(prompt_json)

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
            regex_pattern=pattern_spec.regex_pattern,
            delimiter_type=pattern_spec.delimiter_type,
            amount_factor=pattern_spec.amount_factor,
            date_format=pattern_spec.date_format,
            samples=samples,
            top_matches=top_matches,
            raw_llm_spec=pattern_spec.model_dump(),
            confidence_score=confidence_score,
            confidence_explanation=confidence_explanation,
        )
