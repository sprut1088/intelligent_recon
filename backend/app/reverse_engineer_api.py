from __future__ import annotations

import io
import re
import statistics
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/reverse-engineer", tags=["reverse-engineer"])


class MatchedPair(BaseModel):
    camt_end_to_end_id: str
    camt_amount: float
    camt_booking_date: str
    camt_direction: str

    flat_raw_line: str
    flat_extracted_id: Optional[str]
    flat_extracted_amount: Optional[float]
    flat_extracted_date: Optional[str]
    flat_direction_hint: Optional[str]

    amount_match: bool
    date_match: bool
    direction_match: Optional[bool]


class ConfidenceBreakdown(BaseModel):
    structural_consistency: float
    data_integrity: float
    edge_case_resilience: float
    financial_reconciliation: float


class ReconcileResponse(BaseModel):
    markdown_table: str
    confidence_score: float
    confidence_breakdown: ConfidenceBreakdown
    regex_pattern: str
    structure_type: str
    delimiter: Optional[str] = None
    field_positions: Optional[Dict[str, Any]] = None
    matches: List[MatchedPair]


class FormatAnalyzer:
    """Reverse-engineer an unknown flat payment file using a CAMT.053 XML as reference."""

    def __init__(self, max_sample: int = 10) -> None:
        self.max_sample = max_sample

    # CAMT parsing

    def parse_camt_sample(self, xml_bytes: bytes) -> List[Dict[str, Any]]:
        tree = ET.parse(io.BytesIO(xml_bytes))
        root = tree.getroot()
        ns_strip = lambda t: t.split("}")[-1]

        entries = [n for n in root.iter() if ns_strip(n.tag) == "Ntry"]

        txns: List[Dict[str, Any]] = []

        for entry in entries:
            amt_el = None
            cdt_dbt_el = None
            date_el = None
            e2e_el = None

            for n in entry.iter():
                tag = ns_strip(n.tag)
                if tag == "Amt" and amt_el is None:
                    amt_el = n
                elif tag == "CdtDbtInd" and cdt_dbt_el is None:
                    cdt_dbt_el = n
                elif tag in ("Dt", "BookgDt") and date_el is None:
                    date_el = n
                elif tag == "EndToEndId" and e2e_el is None:
                    e2e_el = n

            if amt_el is None:
                continue

            amt_raw = (amt_el.text or "").strip().replace(",", "")
            try:
                amount = float(amt_raw)
            except ValueError:
                amount = 0.0

            end_to_end_id = (e2e_el.text or "").strip() if e2e_el is not None else ""
            cdt_dbt = (cdt_dbt_el.text or "").strip().upper() if cdt_dbt_el is not None else ""
            if cdt_dbt in {"CRDT", "CREDIT"}:
                cdt_dbt = "CR"
            elif cdt_dbt in {"DBIT", "DEBIT"}:
                cdt_dbt = "DR"

            booking_date = (date_el.text or "").strip() if date_el is not None else ""

            if not end_to_end_id:
                continue
            txns.append(
                {
                    "end_to_end_id": end_to_end_id,
                    "amount": amount,
                    "booking_date": booking_date,
                    "cdt_dbt": cdt_dbt,
                }
            )
            if len(txns) >= self.max_sample:
                break

        if not txns:
            raise ValueError("No suitable CAMT transactions with EndToEndId found")

        return txns

    # Flat file structure detection

    def _detect_delimiter(self, lines: List[str]) -> Optional[str]:
        candidates = [",", ";", "|", "\t"]
        for cand in candidates:
            splits = [len(line.split(cand)) for line in lines if cand in line]
            if not splits:
                continue
            if max(splits) == min(splits) and max(splits) > 1:
                return cand
        return None

    def _is_fixed_width_candidate(self, lines: List[str]) -> bool:
        lengths = [len(l.rstrip("\n")) for l in lines if l.strip()]
        if not lengths:
            return False
        return max(lengths) - min(lengths) <= 3

    # Regex construction

    def _build_id_pattern(self, ids: List[str]) -> str:
        """
        Build an ID pattern using raw EndToEndId values without normalisation.

        We intentionally do NOT strip hyphens or other formatting characters, so the
        inferred regex matches what actually appears in the PSR / flat file.
        """
        unique_ids = sorted({i for i in ids if i})
        if not unique_ids:
            # Fallback – generic ID capture, still allowing hyphens
            return r"(?P<id>[A-Za-z0-9\-]{6,})"

        alternation = "|".join(re.escape(i) for i in unique_ids)
        # Match the raw IDs exactly; no extra padding tokens added around them
        return rf"(?P<id>(?:{alternation}))"

    def _build_amount_pattern(self, amounts: List[float]) -> str:
        has_fraction = any((a * 100) % 100 != 0 for a in amounts)
        if has_fraction:
            return r"(?P<amount>\d{1,12}(?:\.\d{1,4})?)"
        return r"(?P<amount>\d{3,14})"

    def _build_date_pattern(self, dates: List[str]) -> str:
        sample = [d for d in dates if d]
        if not sample:
            return r"(?P<date>\d{8}|\d{4}-\d{2}-\d{2})"
        s = sample[0]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return r"(?P<date>\d{4}-\d{2}-\d{2}|\d{8})"
        if re.fullmatch(r"\d{8}", s):
            return r"(?P<date>\d{8})"
        return r"(?P<date>\d{8}|\d{4}-\d{2}-\d{2})"

    def build_regex(self, camt_txns: List[Dict[str, Any]]) -> str:
        """
        Build a regex that matches the raw EndToEndId as it appears in the flat file,
        then date and amount somewhere after it on the same line.

        No normalisation of the ID is performed; CAMT EndToEndId formatting (e.g.
        TX-2027-0001) is preserved so that the regex aligns with PSR lines like:

            20TX-2027-000120260610PMT-REF-30001...000000002500...
        """
        ids = [t["end_to_end_id"] for t in camt_txns if t.get("end_to_end_id")]
        amounts = [t["amount"] for t in camt_txns]
        dates = [t["booking_date"] for t in camt_txns]

        id_pat = self._build_id_pattern(ids)
        amt_pat = self._build_amount_pattern(amounts)
        date_pat = self._build_date_pattern(dates)

        # Heuristic ordering: ID appears first, then date, then amount later on the line.
        pattern = rf"{id_pat}.*?{date_pat}.*?{amt_pat}"
        return pattern

    # Matching and scoring

    def _parse_flat_amount(self, amount_str: str, implied_decimals: bool) -> float:
        if not amount_str:
            return 0.0
        s = amount_str.replace(",", "")
        if implied_decimals and s.isdigit() and len(s) >= 3:
            return float(s[:-2] + "." + s[-2:])
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _normalise_date(self, date_str: str) -> str:
        s = date_str.strip()
        if re.fullmatch(r"\d{8}", s):
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        return s

    def analyze(self, camt_xml_bytes: bytes, flat_bytes: bytes) -> ReconcileResponse:
        camt_txns = self.parse_camt_sample(camt_xml_bytes)

        flat_text = flat_bytes.decode("utf-8", errors="replace")
        lines = [l.rstrip("\n") for l in flat_text.splitlines() if l.strip()]
        if not lines:
            raise ValueError("Flat file is empty or whitespace only")

        # Heuristic: always treat the first non-empty line as a header and exclude it
        data_lines = lines[1:] if len(lines) > 1 else []
        if not data_lines:
            raise ValueError("Flat file has no data lines after header")

        sample_lines = data_lines[:200]

        delimiter = self._detect_delimiter(sample_lines)
        if delimiter:
            structure_type = "DELIMITED"
        elif self._is_fixed_width_candidate(sample_lines):
            structure_type = "FIXED_WIDTH"
        else:
            structure_type = "UNKNOWN"

        regex_pattern = self.build_regex(camt_txns)
        compiled = re.compile(regex_pattern)

        flat_amount_samples = []
        for line in sample_lines:
            for m in re.finditer(r"\d{3,14}", line):
                flat_amount_samples.append(m.group(0))
                if len(flat_amount_samples) >= 50:
                    break
            if len(flat_amount_samples) >= 50:
                break
        implied_decimals = False
        if flat_amount_samples:
            dot_ratio = sum(1 for a in flat_amount_samples if "." in a) / len(flat_amount_samples)
            implied_decimals = dot_ratio < 0.1

        matches: List[MatchedPair] = []
        used_line_idx = set()

        for txn in camt_txns:
            txn_id = txn["end_to_end_id"]
            txn_amt = txn["amount"]
            txn_date = self._normalise_date(txn["booking_date"])
            txn_dir = txn["cdt_dbt"]

            id_token = re.sub(r"[^A-Za-z0-9]", "", txn_id)
            id_token_short = id_token[-10:] if len(id_token) > 10 else id_token

            best_line_idx = None
            best_score = 0.0
            best_match_obj = None

            # Enumerate over data_lines; map back to original index in `lines` via +1 offset
            for data_idx, line in enumerate(data_lines):
                idx = data_idx + 1
                if idx in used_line_idx:
                    continue
                if id_token_short and id_token_short.lower() not in re.sub(r"[^a-z0-9]", "", line.lower()):
                    continue
                m = compiled.search(line)
                if not m:
                    continue
                flat_id_clean = re.sub(
                    r"[^A-Za-z0-9]",
                    "",
                    (m.group("id") or "") if "id" in m.groupdict() else "",
                )
                overlap = len(set(id_token_short.lower()) & set(flat_id_clean.lower()))
                score = overlap / max(len(id_token_short) or 1, 1)
                if score > best_score:
                    best_score = score
                    best_line_idx = idx
                    best_match_obj = m

            if best_line_idx is None or best_match_obj is None:
                continue

            used_line_idx.add(best_line_idx)
            line = lines[best_line_idx]
            m = best_match_obj

            flat_id = m.group("id") if "id" in m.groupdict() else None
            flat_amt_raw = m.group("amount") if "amount" in m.groupdict() else None
            flat_date_raw = m.group("date") if "date" in m.groupdict() else None

            flat_amt = self._parse_flat_amount(
                flat_amt_raw or "", implied_decimals=implied_decimals
            )
            flat_date = self._normalise_date(flat_date_raw or "")

            amount_match = abs(flat_amt - txn_amt) < 0.01
            date_match = (flat_date == txn_date) or (
                flat_date_raw == txn["booking_date"]
            )
            direction_match = None

            matches.append(
                MatchedPair(
                    camt_end_to_end_id=txn_id,
                    camt_amount=txn_amt,
                    camt_booking_date=txn["booking_date"],
                    camt_direction=txn_dir,
                    flat_raw_line=line,
                    flat_extracted_id=flat_id,
                    flat_extracted_amount=flat_amt,
                    flat_extracted_date=flat_date_raw,
                    flat_direction_hint=None,
                    amount_match=amount_match,
                    date_match=date_match,
                    direction_match=direction_match,
                )
            )

        if matches:
            amount_match_ratio = sum(1 for m in matches if m.amount_match) / len(matches)
            date_match_ratio = sum(1 for m in matches if m.date_match) / len(matches)
        else:
            amount_match_ratio = 0.0
            date_match_ratio = 0.0

        hit_lines = sum(1 for l in sample_lines if compiled.search(l))
        structural_consistency = 0.0
        if sample_lines:
            structural_consistency = 100.0 * hit_lines / len(sample_lines)
            if structure_type == "UNKNOWN":
                structural_consistency *= 0.7

        data_integrity = 100.0 * (0.6 * amount_match_ratio + 0.4 * date_match_ratio)

        edge_case_resilience = 0.0
        if matches:
            id_lens = [len((m.flat_extracted_id or "")) for m in matches]
            if len(id_lens) > 1:
                stdev = statistics.pstdev(id_lens)
                edge_case_resilience = max(0.0, 100.0 - stdev * 10.0)
            else:
                edge_case_resilience = 80.0

        financial_reconciliation = 100.0 * amount_match_ratio

        overall_confidence = (
            0.30 * structural_consistency
            + 0.30 * data_integrity
            + 0.20 * edge_case_resilience
            + 0.20 * financial_reconciliation
        )

        breakdown = ConfidenceBreakdown(
            structural_consistency=round(structural_consistency, 2),
            data_integrity=round(data_integrity, 2),
            edge_case_resilience=round(edge_case_resilience, 2),
            financial_reconciliation=round(financial_reconciliation, 2),
        )

        header = (
            "| CAMT EndToEndId | CAMT Amount | CAMT Booking Date | Flat Amount | Flat Date | Amount Match | Date Match |\n"
            "|-----------------|------------:|-------------------|------------:|-----------|--------------|-----------|\n"
        )
        rows_md: List[str] = []
        for m in matches:
            rows_md.append(
                f"| {m.camt_end_to_end_id} "
                f"| {m.camt_amount:.2f} "
                f"| {m.camt_booking_date} "
                f"| {m.flat_extracted_amount if m.flat_extracted_amount is not None else ''} "
                f"| {m.flat_extracted_date or ''} "
                f"| {'✅' if m.amount_match else '❌'} "
                f"| {'✅' if m.date_match else '❌'} |"
            )
        markdown_table = (
            header + "\n".join(rows_md)
            if rows_md
            else header + "| _no matches found_ | | | | | | |"
        )

        field_positions: Dict[str, Any] = {
            "pattern_order": ["id", "date", "amount"],
            "implied_decimals": implied_decimals,
        }

        return ReconcileResponse(
            markdown_table=markdown_table,
            confidence_score=round(overall_confidence, 2),
            confidence_breakdown=breakdown,
            regex_pattern=regex_pattern,
            structure_type=structure_type,
            delimiter=delimiter,
            field_positions=field_positions,
            matches=matches,
        )


@router.post("/reconcile", response_model=ReconcileResponse)
async def reconcile_files(
    camt_file: UploadFile = File(...),
    flat_file: UploadFile = File(...),
) -> ReconcileResponse:
    """Reverse-engineer flat file format using a CAMT.053 XML reference."""
    camt_bytes = await camt_file.read()
    flat_bytes = await flat_file.read()
    if not camt_bytes:
        raise HTTPException(status_code=400, detail="Empty camt_file")
    if not flat_bytes:
        raise HTTPException(status_code=400, detail="Empty flat_file")

    analyzer = FormatAnalyzer(max_sample=10)
    try:
        return analyzer.analyze(camt_bytes, flat_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

