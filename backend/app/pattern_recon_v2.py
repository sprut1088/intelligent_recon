from __future__ import annotations

from typing import Any, Dict, List, Set, Optional

import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import ValidationError

from .reverse_engineer_llm import (
    LlmMatchedPair,
    LlmReverseEngineerService,
)
from .reverse_engineer_schemas import RegexSummary, ReconPatternRow, ReconPatternsResponse
from .config import settings

router = APIRouter(prefix="/api/reverse-engineer", tags=["reverse-engineer-v2"])


def _build_regex_summary_placeholder() -> RegexSummary:
    """
    Minimal RegexSummary placeholder for v2 API.

    We keep this simple and backward compatible for now; the main focus
    of patternreconv2 is the waterfall-based pattern taxonomy rather than
    regex discovery itself.
    """
    return RegexSummary(
        regex_pattern="",
        delimiter_type="UNKNOWN",
        amount_factor=1.0,
        date_format="UNKNOWN",
        samples=[],
        top_matches=[],
    )


def _build_top_matches(
    service: LlmReverseEngineerService,
    camt_xml_bytes: bytes,
    flat_bytes: bytes,
) -> List[LlmMatchedPair]:
    """
    Reuse the existing matching pipeline to obtain a simplified view of
    top CAMT↔flat-line pairs, expressed as LlmMatchedPair instances.
    """
    camt_txs = service._parse_camt_from_bytes(camt_xml_bytes)
    if not camt_txs:
        raise ValueError("No CAMT transactions found for recon pattern aggregation v2")

    flat_lines = service._flat_lines_from_bytes(flat_bytes)
    if not flat_lines:
        raise ValueError("Flat file is empty or whitespace only")

    llm_examples: Dict[str, Any] = service._build_llm_examples(camt_txs, flat_lines)
    top_matches_raw: List[Dict[str, Any]] = llm_examples.get("top_matches", []) or []

    top_matches: List[LlmMatchedPair] = []
    for item in top_matches_raw:
        try:
            top_matches.append(LlmMatchedPair.model_validate(item))
        except ValidationError:
            continue
    return top_matches


def _build_psr_dataset_from_bytes(flat_bytes: bytes, regex_pattern: str) -> List[Dict[str, Any]]:
    """
    Build a PSR/PMT dataset from raw bytes using the provided regex_pattern.

    For now this is internal to pattern_recon_v2; it returns a list of dicts,
    one per non-empty line that matches the regex. Each dict contains:
      - __raw_line: the original line
      - __line_number: 1-based line index in the flat file
      - one key per regex named group, if any.

    If no named groups are defined in the regex, the dicts will just have
    __raw_line and __line_number.
    """
    try:
        if not regex_pattern:
            raise ValueError("regex_pattern is required to build PSR dataset")
        pattern = re.compile(regex_pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex_pattern for PSR dataset: {exc}") from exc

    text = flat_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()

   
    dataset: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        raw = line.rstrip("\n\r")
        if not raw.strip():
            continue

        m = pattern.search(raw)
        if not m:
            # Skip lines that don't match the regex for now
            continue

        row: Dict[str, Any] = {
            "__raw_line": raw,
            "__line_number": idx,
        }

        # Prefer named groups to get a structured dict
        groupdict = m.groupdict()
        print("groupdict", groupdict)
        if groupdict:
            # Trim trailing/leading whitespace from all captured groups
            cleaned = {
                k: (v.strip() if isinstance(v, str) else v)
                for k, v in groupdict.items()
            }
            row.update(cleaned)

        dataset.append(row)

    return dataset


def _build_camt_dataset_from_bytes(
    service: LlmReverseEngineerService,
    camt_xml_bytes: bytes,
) -> List[Dict[str, Any]]:
    """
    Build a CAMT dataset from raw XML bytes.

    This uses the existing LlmReverseEngineerService parsing logic and
    exposes a flattened dict per transaction with commonly-used fields.
    For now we only surface a pragmatic subset; this can be expanded later.
    """
    camt_txs = service._parse_camt_from_bytes(camt_xml_bytes)
    if not camt_txs:
        raise ValueError("No CAMT transactions found while building CAMT dataset")

    dataset: List[Dict[str, Any]] = []
    for tx in camt_txs:
        # tx is expected to be a CamtTransaction model from reverse_engineer.models
        row: Dict[str, Any] = {}

        # Core identifiers and dates
        row["transaction_id"] = getattr(tx, "transaction_id", None)
        row["booking_date"] = (
            tx.booking_date.isoformat() if getattr(tx, "booking_date", None) else None
        )
        row["value_date"] = (
            tx.value_date.isoformat() if getattr(tx, "value_date", None) else None
        )

        # Amount and currency
        row["amount"] = getattr(tx, "amount", None)
        row["currency"] = getattr(tx, "currency", None)

        # References (flatten a few common ones if available)
        refs = getattr(tx, "references", None)
        if refs is not None:
            # Canonical single-valued CAMT references exposed as friendly keys
            row["end_to_end_id"] = getattr(refs, "end_to_end_id", None)
            row["acct_svcr_ref"] = getattr(refs, "acct_svcr_ref", None)
            row["uetr"] = getattr(refs, "uetr", None)
            # Map underlying mndt_id / instr_id to friendlier names
            row["mandate_id"] = getattr(refs, "mndt_id", None)
            row["instruction_id"] = getattr(refs, "instr_id", None)
            row["tx_id"] = getattr(refs, "tx_id", None)
            row["pmt_inf_id"] = getattr(refs, "pmt_inf_id", None)
            row["invoice_ref"] = getattr(refs, "invoice_ref", None)
            # Multi-valued generic reference-like fields
            row["other_refs"] = getattr(refs, "other_refs", None)

        # Remittance and counterparties – keep as nested objects for now
        row["remittance"] = getattr(tx, "remittance", None)
        row["counterparties"] = getattr(tx, "counterparties", None)

        dataset.append(row)

    return dataset


@router.post("/patternreconv2", response_model=ReconPatternsResponse)
async def pattern_recon_v2(
    camt_file: UploadFile = File(...),
    flat_file: UploadFile = File(...),
    regex_pattern: str = "",
) -> ReconPatternsResponse:
    """
    Waterfall-based reconciliation pattern discovery v2 (Stage 1 only).

    This initial implementation focuses on exact-reference patterns using
    reference-like signals from the MatchingEngine (EndToEndId, AcctSvcrRef,
    UETR, generic structured references, invoice-like references).

    Flow:
      1. Parse CAMT.053 and flat file into internal models.
      2. Use the existing matching engine to obtain high-confidence
         CAMT↔flat-line pairs (LlmMatchedPair).
      3. Run a MASTER_LEVEL_1 waterfall over reference-type signals,
         generating a separate ReconPatternRow per reference type:
            - END_TO_END_ID_EXACT
            - ACCT_SVCR_REF_EXACT
            - UETR_EXACT
            - GENERIC_REF_EXACT
            - INVOICE_REF_EXACT
         Each pattern consumes its matched CAMT and PSR records so that
         subsequent patterns only see the residual unmatched population.
      4. Return a ReconPatternsResponse with RegexSummary placeholder
         and the discovered pattern rows.
    """
    camt_bytes = await camt_file.read()
    flat_bytes = await flat_file.read()
    

    if not camt_bytes:
        raise HTTPException(status_code=400, detail="Empty camt_file")
    if not flat_bytes:
        raise HTTPException(status_code=400, detail="Empty flat_file")

    # ------------------------------------------------------------------
    # Internal-only datasets for CAMT and PSR/PMT, built immediately
    # after reading bytes, before initiating LlmReverseEngineerService
    # / matching engine usage.
    # ------------------------------------------------------------------
    try:
        # Build CAMT dataset directly from the XML bytes
        # (uses the same underlying parsing logic as the LLM reverse
        # engineering service, but is independent of its instantiation).
        service_for_camt = LlmReverseEngineerService()
        camt_dataset = _build_camt_dataset_from_bytes(service_for_camt, camt_bytes)

        # Build PSR/PMT dataset purely from the flat bytes + regex
        psr_dataset = _build_psr_dataset_from_bytes(flat_bytes, regex_pattern)

        print(f"Built CAMT dataset with {len(camt_dataset)} rows (pre-LLM service)")
        print(f"Built PSR dataset with {len(psr_dataset)} rows using regex (pre-LLM service)")
        print("camt data set", camt_dataset)
        print("psr data set", psr_dataset)
    except ValueError as exc:
        # Surface as 400 so the caller knows the input/regex was bad
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Now initiate the LlmReverseEngineerService for matching / patterns.
    service = LlmReverseEngineerService()

    try:
        print("Building top matches for CAMT↔flat-line pairs...")
        top_matches_models = _build_top_matches(service, camt_bytes, flat_bytes)
        print
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Record-consumption sets: once a CAMT or PSR id is matched under a pattern,
    # it is removed from the working population for subsequent patterns.
    matched_camt_ids: Set[str] = set()
    matched_psr_ids: Set[str] = set()

    def residual_pairs() -> List[LlmMatchedPair]:
        return [
            m
            for m in top_matches_models
            if m.camt_transaction_id not in matched_camt_ids
            and f"LINE-{m.flat_line_number}" not in matched_psr_ids
        ]

    recon_rows: List[ReconPatternRow] = []

    def extract_amounts_from_pair(m: LlmMatchedPair) -> Optional[tuple[float, float]]:
        """
        Extract comparable bank/internal amounts from a matched pair.

        Adjust the attribute paths here based on your actual LlmMatchedPair model:
          - left/bank/CAMT side
          - right/internal/flat side
        """
        try:
            # Example: if LlmMatchedPair has camt_transaction and flat_line models
            left = getattr(m.camt_transaction, "amount", None)
            right = getattr(m.flat_line, "amount", None)
        except AttributeError:
            return None

        if left is None or right is None:
            return None

        try:
            return float(left), float(right)
        except (TypeError, ValueError):
            return None

    def analyze_amount_mismatches_for_pairs(
        pairs: List[LlmMatchedPair],
        subtype: str,
        base_description: str,
    ) -> Optional[ReconPatternRow]:
        """
        For a given reference signal’s matched pairs:
        - Use settings.minor_variance_tolerance
        - Find those where |bank - internal| > tolerance
        - Build a ReconPatternRow for these “pending missed” entries
          that fail exact-amount/tolerance logic.
        """
        if not pairs:
            return None

        mismatches: List[LlmMatchedPair] = []
        example_psr_ids: List[str] = []
        example_camt_ids: List[str] = []
        bank_sum = 0.0
        internal_sum = 0.0

        for m in pairs:
            amts = extract_amounts_from_pair(m)
            if amts is None:
                continue

            left_amt, right_amt = amts
            diff = abs(left_amt - right_amt)
            if diff <= settings.minor_variance_tolerance:
                # Within tolerance – not a “pending missed” case
                continue

            mismatches.append(m)
            psr_id = f"LINE-{m.flat_line_number}"
            camt_id = m.camt_transaction_id

            if len(example_psr_ids) < 5 and psr_id not in example_psr_ids:
                example_psr_ids.append(psr_id)
            if len(example_camt_ids) < 5 and camt_id not in example_camt_ids:
                example_camt_ids.append(camt_id)

            bank_sum += left_amt
            internal_sum += right_amt

        if not mismatches:
            return None

        return ReconPatternRow(
            pattern_level="MASTER_LEVEL_1",
            pattern_subtype=f"{subtype}_AMOUNT_MISMATCH_BEYOND_TOLERANCE",
            description=(
                f"{base_description} where amount variance exceeds minor tolerance "
                f"({settings.minor_variance_tolerance}). These are candidates for "
                f"tolerance calibration / review and represent the 'pending missed' "
                f"entries that did not satisfy exact-amount flow."
            ),
            case_count=len(mismatches),
            bank_sum=bank_sum,
            internal_sum=internal_sum,
            example_psr_ids=example_psr_ids,
            example_camt_ids=example_camt_ids,
        )

    def add_exact_ref_pattern(
        signal_name: str,
        subtype: str,
        description: str,
    ) -> None:
        """
        Base helper: bucket pairs by a single reference signal name
        (e.g. 'end_to_end_id', 'acct_svcr_ref', 'uetr', 'invoice_ref').
        Keeps the existing behaviour for these explicit signals.
        """
        pairs = [
            m for m in residual_pairs() if signal_name in (m.matched_signals or [])
        ]
        if not pairs:
            return

        case_count = len(pairs)
        example_psr_ids: List[str] = []
        example_camt_ids: List[str] = []

        for m in pairs:
            psr_id = f"LINE-{m.flat_line_number}"
            camt_id = m.camt_transaction_id
            if len(example_psr_ids) < 5 and psr_id not in example_psr_ids:
                example_psr_ids.append(psr_id)
            if len(example_camt_ids) < 5 and camt_id not in example_camt_ids:
                example_camt_ids.append(camt_id)

        # Base pattern: exact-reference matches (regardless of amount variance)
        recon_rows.append(
            ReconPatternRow(
                pattern_level="MASTER_LEVEL_1",
                pattern_subtype=subtype,
                description=description,
                case_count=case_count,
                bank_sum=0.0,
                internal_sum=0.0,
                example_psr_ids=example_psr_ids,
                example_camt_ids=example_camt_ids,
            )
        )

        # Additional pattern row: pending missed entries where amount is outside tolerance
        mismatch_row = analyze_amount_mismatches_for_pairs(
            pairs=pairs,
            subtype=subtype,
            base_description=description,
        )
        if mismatch_row is not None:
            recon_rows.append(mismatch_row)

        # Consume the records so they do not participate in later patterns
        for m in pairs:
            matched_camt_ids.add(m.camt_transaction_id)
            matched_psr_ids.add(f"LINE-{m.flat_line_number}")

    def add_generic_exact_ref_patterns() -> None:
        """
        Build patterns for generic exact references using the actual CAMT ref tag
        that matched, instead of a single GENERIC_REF_EXACT bucket.

        Uses raw_signals.exact_ref_matches_by_field where available.
        """
        # Start from residual pairs that have an 'exact_reference' signal.
        pairs = [
            m for m in residual_pairs() if "exact_reference" in (m.matched_signals or [])
        ]
        if not pairs:
            return

        # Bucket by (field_name, reference_value)
        buckets: Dict[tuple[str, str], Dict[str, Any]] = {}

        for m in pairs:
            raw_sig_dict: Dict[str, Any] | None = getattr(m, "raw_signals", None)
            field_map: Dict[str, List[str]] = {}
            if raw_sig_dict and isinstance(raw_sig_dict, dict):
                raw_field_map = raw_sig_dict.get("exact_ref_matches_by_field") or {}
                if isinstance(raw_field_map, dict):
                    for k, v in raw_field_map.items():
                        if isinstance(v, list):
                            field_map[k] = v

            if not field_map:
                # Fall back to a generic bucket if we have no per-field breakdown
                key = ("GENERIC_REF", "UNKNOWN")
                buckets.setdefault(
                    key,
                    {
                        "pattern_level": "MASTER_LEVEL_1",
                        "pattern_subtype": "GENERIC_REF_EXACT",
                        "description": (
                            "Exact structured reference matches where the specific "
                            "Camt reference field is not available."
                        ),
                        "case_count": 0,
                        "bank_sum": 0.0,
                        "internal_sum": 0.0,
                        "example_psr_ids": [],
                        "example_camt_ids": [],
                    },
                )
                b = buckets[key]
                b["case_count"] += 1
                psr_id = f"LINE-{m.flat_line_number}"
                camt_id = m.camt_transaction_id
                if len(b["example_psr_ids"]) < 5 and psr_id not in b["example_psr_ids"]:
                    b["example_psr_ids"].append(psr_id)
                if len(b["example_camt_ids"]) < 5 and camt_id not in b["example_camt_ids"]:
                    b["example_camt_ids"].append(camt_id)
                continue

            for field_name, values in field_map.items():
                for val in values:
                    key = (field_name, str(val))
                    human_field = field_name
                    subtype = f"EXACT_REF_{field_name.upper()}"
                    desc = f"Exact matches on CAMT reference field {human_field} = {val}."
                    bucket = buckets.setdefault(
                        key,
                        {
                            "pattern_level": "MASTER_LEVEL_1",
                            "pattern_subtype": subtype,
                            "description": desc,
                            "case_count": 0,
                            "bank_sum": 0.0,
                            "internal_sum": 0.0,
                            "example_psr_ids": [],
                            "example_camt_ids": [],
                        },
                    )
                    bucket["case_count"] += 1
                    psr_id = f"LINE-{m.flat_line_number}"
                    camt_id = m.camt_transaction_id
                    if len(bucket["example_psr_ids"]) < 5 and psr_id not in bucket["example_psr_ids"]:
                        bucket["example_psr_ids"].append(psr_id)
                    if len(bucket["example_camt_ids"]) < 5 and camt_id not in bucket["example_camt_ids"]:
                        bucket["example_camt_ids"].append(camt_id)

        # Materialise buckets into ReconPatternRow objects and append
        for bucket in buckets.values():
            if bucket["case_count"] <= 0:
                continue
            recon_rows.append(ReconPatternRow(**bucket))

        # For now, just consume these records so they do not participate in later patterns.
        for m in pairs:
            matched_camt_ids.add(m.camt_transaction_id)
            matched_psr_ids.add(f"LINE-{m.flat_line_number}")

    def add_pmt_ref_plus_amount_pattern(
        signal_name: str,
        subtype: str,
        description: str,
    ) -> None:
        """
        Pattern: PMT-REF (from CAMT Ustrd) + amount within tolerance.

        We:
        - Filter residual pairs by the PMT-REF signal.
        - Require amount to be present on both sides.
        - Build a base pattern row for pairs where amount is within tolerance.
        - Build an additional row for same PMT-REF but amount beyond tolerance
          (pending missed entries).
        """
        print(f"Analyzing PMT-REF + amount patterns for signal '{signal_name}'...")
        all_pmt_pairs = [
            m for m in residual_pairs() if signal_name in (m.matched_signals or [])
        ]
        print(f"Found {len(all_pmt_pairs)} pairs for PMT-REF signal '{signal_name}'")
        if not all_pmt_pairs:
            return

        within_tolerance_pairs: List[LlmMatchedPair] = []
        example_psr_ids: List[str] = []
        example_camt_ids: List[str] = []

        for m in all_pmt_pairs:
            amts = extract_amounts_from_pair(m)
            if amts is None:
                continue

            left_amt, right_amt = amts
            diff = abs(left_amt - right_amt)
            if diff <= settings.minor_variance_tolerance:
                within_tolerance_pairs.append(m)
                psr_id = f"LINE-{m.flat_line_number}"
                camt_id = m.camt_transaction_id

                if len(example_psr_ids) < 5 and psr_id not in example_psr_ids:
                    example_psr_ids.append(psr_id)
                if len(example_camt_ids) < 5 and camt_id not in example_camt_ids:
                    example_camt_ids.append(camt_id)

        # Base pattern: PMT-REF + amount within tolerance
        if within_tolerance_pairs:
            recon_rows.append(
                ReconPatternRow(
                    pattern_level="MASTER_LEVEL_1",
                    pattern_subtype=subtype,
                    description=description,
                    case_count=len(within_tolerance_pairs),
                    bank_sum=0.0,
                    internal_sum=0.0,
                    example_psr_ids=example_psr_ids,
                    example_camt_ids=example_camt_ids,
                )
            )

        # Additional pattern row: PMT-REF matches but amount beyond tolerance
        mismatch_row = analyze_amount_mismatches_for_pairs(
            pairs=all_pmt_pairs,
            subtype=subtype,
            base_description=description,
        )
        if mismatch_row is not None:
            recon_rows.append(mismatch_row)

        # Consume all pairs that participated in PMT-REF-based matching
        for m in all_pmt_pairs:
            matched_camt_ids.add(m.camt_transaction_id)
            matched_psr_ids.add(f"LINE-{m.flat_line_number}")

    # Stage 1: exact-reference patterns, one pattern per reference field
    print("Building exact-reference patterns...",len(residual_pairs()))
    add_exact_ref_pattern(
        signal_name="end_to_end_id",
        subtype="END_TO_END_ID_EXACT",
        description="Exact EndToEndId matches (P1: Exact EndToEndId Match).",
    )
    print("Building exact-reference patterns... done",len(residual_pairs()))
    add_exact_ref_pattern(
        signal_name="acct_svcr_ref",
        subtype="ACCT_SVCR_REF_EXACT",
        description="Exact AcctSvcrRef / bank reference matches.",
    )
    print("Building UETR_EXACT-reference patterns... done",len(residual_pairs()))
    add_exact_ref_pattern(
        signal_name="uetr",
        subtype="UETR_EXACT",
        description="Exact UETR-based matches.",
    )
    # Generic structured references: build patterns per actual CAMT ref tag
    add_generic_exact_ref_patterns()
    add_exact_ref_pattern(
        signal_name="invoice_ref",
        subtype="INVOICE_REF_EXACT",
        description="Exact invoice reference matches.",
    )
    print("Building INVOICE_REF_EXACT-reference patterns... done",len(residual_pairs()))
    # Stage 1.a: invoice extracted from CAMT remittance (Ustrd) and matched to PSR invoice
    add_exact_ref_pattern(
        signal_name="invoice_from_remittance",  # adjust to actual signal key from matching engine
        subtype="INVOICE_FROM_REMITTANCE_EXACT",
        description="Exact invoice matches where invoice is extracted from CAMT remittance text (Ustrd) and aligned to PSR invoice.",
    )

    # Stage 1.b: PMT-REF (from Ustrd) plus amount within tolerance
    print("Building PMT-REF + amount patterns...",len(residual_pairs()))
    add_pmt_ref_plus_amount_pattern(
        signal_name="pmt_ref",  # adjust to actual signal key emitted from Ustrd parsing
        subtype="PMT_REF_PLUS_AMOUNT",
        description="Matches using payment reference from CAMT Ustrd plus amount within tolerance.",
    )

    regex_summary = _build_regex_summary_placeholder()

    return ReconPatternsResponse(regex_summary=regex_summary, recon_patterns=recon_rows)
