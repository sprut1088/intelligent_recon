from __future__ import annotations

import itertools
import logging
import re

try:
    from rapidfuzz import fuzz as _fuzz
except ImportError:
    _fuzz = None  # type: ignore[assignment]
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import UploadFile

from .config import settings
from .parsers import (
    CamtTransaction,
    PsrTransaction,
    PMT_REF_RE,
    INVOICE_RE,
    invoice_suffix,
    parse_camt_file,
    parse_psr_file,
)

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "_", name or "upload.dat").strip()
    return cleaned or "upload.dat"


def _write_upload_to_temp(upload: UploadFile, temp_dir: Path) -> Path:
    upload.file.seek(0)
    filename = _safe_filename(upload.filename or "upload.dat")
    target_path = temp_dir / filename
    with target_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target_path


def _guess_format(path: Path, content_type: Optional[str]) -> str:
    filename = path.name.lower()
    ct = (content_type or "").lower()
    if filename.endswith(".xml") or "xml" in ct:
        return "XML"
    if filename.endswith(('.txt', '.csv', '.psr')) or ct.startswith("text"):
        return "TEXT"
    return "UNKNOWN"


def _load_camt(path: Path) -> List[CamtTransaction]:
    return parse_camt_file(path)


def _first_text_by_local_name(parent: ET.Element, local_name: str) -> str:
    for item in parent.iter():
        if item.tag.split('}')[-1] == local_name and item.text:
            return item.text.strip()
    return ""


def _load_camt_entries(path: Path) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    root = ET.parse(path).getroot()
    for ntry in root.iter():
        if ntry.tag.split('}')[-1] != "Ntry":
            continue

        refs_map: Dict[str, List[str]] = {}
        txdtls = None
        for el in ntry.iter():
            if el.tag.split('}')[-1] == "TxDtls":
                txdtls = el
                break

        if txdtls is not None:
            refs = next((child for child in txdtls.iter() if child.tag.split('}')[-1] == "Refs"), None)
            if refs is not None:
                for child in list(refs):
                    tag = child.tag.split('}')[-1]
                    if child.text and child.text.strip():
                        refs_map.setdefault(tag, []).append(child.text.strip())

        counterparty = ""
        if txdtls is not None:
            dbtr = next((child for child in txdtls.iter() if child.tag.split('}')[-1] == "Dbtr"), None)
            if dbtr is not None:
                counterparty = _first_text_by_local_name(dbtr, "Nm")

        remittance = ""
        if txdtls is not None:
            rmtinf = next((child for child in txdtls.iter() if child.tag.split('}')[-1] == "RmtInf"), None)
            if rmtinf is not None:
                remittance = _first_text_by_local_name(rmtinf, "Ustrd")

        entries.append({
            "ntry_ref": _first_text_by_local_name(ntry, "NtryRef"),
            "amount": _first_text_by_local_name(ntry, "Amt"),
            "currency": next((el.attrib.get("Ccy", "") for el in ntry.iter() if el.tag.split('}')[-1] == "Amt"), ""),
            "direction": _first_text_by_local_name(ntry, "CdtDbtInd"),
            "booking_date": _first_text_by_local_name(ntry, "Dt"),
            "counterparty": counterparty,
            "remittance": remittance,
            "refs": refs_map,
        })
    return entries


def _extract_camt_refs_map(path: Path) -> Dict[str, set]:
    """Return a map of XML local-name -> set of text values found in the CAMT file.

    This collects identifiers found directly (e.g. InstrId, EndToEndId, NtryRef)
    and also all child tags under any <Refs> container.
    """
    refs_map: Dict[str, set] = {}
    try:
        root = ET.parse(path).getroot()
        for el in root.iter():
            local = el.tag.split('}')[-1]
            # collect direct identifier nodes with text
            if el.text and el.text.strip():
                refs_map.setdefault(local, set()).add(el.text.strip())
            # if this element is a Refs container, also include all its immediate children
            if local == "Refs":
                for child in list(el):
                    child_local = child.tag.split('}')[-1]
                    if child.text and child.text.strip():
                        refs_map.setdefault(child_local, set()).add(child.text.strip())
    except Exception:
        # non-fatal: return whatever we collected
        pass
    return refs_map


# ---------------------------------------------------------------------------
# Large-file-safe CAMT reference index + flat-file scanner
# ---------------------------------------------------------------------------

# Sentinel values that appear in <EndToEndId> and similar fields when the
# originating bank could not populate them — exclude from the index.
_SKIP_REF_VALUES: frozenset = frozenset({
    "NOTFOUND", "NOT FOUND", "N/A", "NOTAVAILABLE", "NONE", "NA",
})


def _build_camt_ref_index(
    path: Path,
) -> tuple:
    """Stream-parse the CAMT XML with iterparse and build a per-entry ref index.

    Only *identifier* values (those found under any ``<Refs>`` child element,
    plus PMT-REF / INV tokens extracted from ``<Ustrd>`` remittance text) are
    collected.  Amounts, dates, and free-text names are intentionally excluded
    to avoid false-positive matches when scanning the flat file.

    This approach is memory-efficient for large CAMT files: ``elem.clear()``
    releases each processed ``<Ntry>`` subtree before moving to the next.

    Returns
    -------
    value_to_entry : dict[str, entry_dict]
        Maps each unique identifier (upper-cased) to the first CAMT entry that
        owns it.  The entry dict contains the same keys as ``_load_camt_entries``.
    all_values : set[str]
        Flat set of all collected identifiers (used to build the combined regex).
    """
    value_to_entry: Dict[str, Dict[str, object]] = {}
    all_values: set = set()

    context = ET.iterparse(str(path), events=("end",))
    for _event, elem in context:
        if elem.tag.split('}')[-1] != "Ntry":
            continue

        ntry_ref     = _first_text_by_local_name(elem, "NtryRef")
        amount       = _first_text_by_local_name(elem, "Amt")
        currency     = next(
            (e.attrib.get("Ccy", "") for e in elem.iter()
             if e.tag.split('}')[-1] == "Amt"),
            "",
        )
        direction    = _first_text_by_local_name(elem, "CdtDbtInd")
        booking_date = _first_text_by_local_name(elem, "Dt")
        counterparty = ""
        remittance   = ""

        txdtls = next(
            (e for e in elem.iter() if e.tag.split('}')[-1] == "TxDtls"), None
        )

        # collect only child tags found inside <Refs>
        refs_map: Dict[str, str] = {}
        if txdtls is not None:
            refs_el = next(
                (e for e in txdtls.iter() if e.tag.split('}')[-1] == "Refs"), None
            )
            if refs_el is not None:
                for child in list(refs_el):
                    tag = child.tag.split('}')[-1]
                    val = (child.text or "").strip()
                    if val and val.upper() not in _SKIP_REF_VALUES:
                        refs_map[tag] = val

            dbtr = next(
                (e for e in txdtls.iter() if e.tag.split('}')[-1] == "Dbtr"), None
            )
            if dbtr is not None:
                counterparty = _first_text_by_local_name(dbtr, "Nm")

            rmtinf = next(
                (e for e in txdtls.iter() if e.tag.split('}')[-1] == "RmtInf"), None
            )
            if rmtinf is not None:
                remittance = _first_text_by_local_name(rmtinf, "Ustrd")

        # extract structured tokens from the remittance free text
        pmt_ref_m = PMT_REF_RE.search(remittance)
        inv_m     = INVOICE_RE.search(remittance)
        pmt_ref   = pmt_ref_m.group(0).upper() if pmt_ref_m else ""
        invoice   = inv_m.group(0).upper().replace(" ", "-") if inv_m else ""

        entry: Dict[str, object] = {
            "ntry_ref":    ntry_ref,
            "amount":      amount,
            "currency":    currency,
            "direction":   direction,
            "booking_date": booking_date,
            "counterparty": counterparty,
            "remittance":  remittance,
            "refs":        refs_map,
            "pmt_ref":     pmt_ref,
            "invoice":     invoice,
        }

        id_values: set = set()
        id_values.update(v for v in refs_map.values() if v)
        if pmt_ref:
            id_values.add(pmt_ref)
        if invoice:
            id_values.add(invoice)

        for val in id_values:
            upper_val = val.upper()
            if upper_val not in value_to_entry:
                value_to_entry[upper_val] = entry
        all_values.update(v.upper() for v in id_values)

        # release the processed subtree so memory does not accumulate
        elem.clear()

    logger.debug("CAMT ref index built: %d unique identifiers", len(all_values))
    return value_to_entry, all_values


def _scan_flat_file_for_refs(
    path: Path,
    value_to_entry: Dict[str, Dict[str, object]],
    all_values: set,
    max_matches: int = 500,
) -> List[Dict[str, object]]:
    """Stream a flat file and find every line that contains a CAMT ref value.

    A *single* combined regex built from all ref values is used so that each
    line requires only one pass regardless of how many CAMT entries exist.
    The file is streamed line-by-line — the full file is never held in memory.

    Parameters
    ----------
    max_matches :
        Stop collecting after this many matched lines to keep the response
        payload small for very large files.
    """
    if not all_values:
        return []

    # sort longest-first so longer tokens shadow overlapping shorter ones
    sorted_vals = sorted(all_values, key=len, reverse=True)
    combined_re = re.compile(
        "|".join(re.escape(v) for v in sorted_vals),
        re.IGNORECASE,
    )

    matches: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if len(matches) >= max_matches:
                break
            line = raw.rstrip("\n")
            hits = combined_re.findall(line)
            if not hits:
                continue

            matched_entries: List[Dict[str, object]] = []
            seen: set = set()
            for hit in hits:
                key = hit.upper()
                if key in seen:
                    continue
                seen.add(key)
                entry = value_to_entry.get(key)
                if entry:
                    matched_entries.append({"value": hit, "camt_entry": entry})

            if matched_entries:
                matches.append({
                    "line_no": line_no,
                    "line": line,
                    "matched": matched_entries,
                })

    logger.debug(
        "Flat-file scan: %d lines matched (cap=%d)", len(matches), max_matches
    )
    return matches


def _infer_flat_file_format(matched_records: List[Dict[str, object]]) -> Dict[str, object]:
    """Derive the flat-file format from the set of matched lines.

    Analyses structural features of the matched lines (2-char record-type
    prefixes, delimiter frequency, character offsets of the matched ref values)
    rather than assuming any particular spec, so it adapts to any flat-file
    layout.

    Returns
    -------
    dict with keys:
        detected_type   – "FIXED_WIDTH" | "DELIMITED" | "UNKNOWN"
        record_prefix   – dominant 2-char line prefix, e.g. "20"
        delimiter       – "," | "\\t" | "|" | ";" | None
        field_positions – {name: offset} for fixed-width layouts
        suggested_regex_map – {field: pattern} ready for use as regex hints
        sample_lines    – up to 5 representative matched lines
    """
    if not matched_records:
        return {
            "detected_type": "UNKNOWN",
            "record_prefix": None,
            "delimiter": None,
            "field_positions": {},
            "suggested_regex_map": {},
            "sample_lines": [],
        }

    lines = [r["line"] for r in matched_records[:200]]
    sample_lines = lines[:5]

    # delimiter detection: count how many lines contain each candidate
    delim_hits: Dict[str, int] = {",": 0, "\t": 0, "|": 0, ";": 0}
    for line in lines:
        for d in delim_hits:
            if d in line:
                delim_hits[d] += 1
    dominant_delim = max(delim_hits, key=lambda d: delim_hits[d])
    is_delimited = delim_hits[dominant_delim] >= len(lines) * 0.8

    # 2-char record-type prefix detection
    prefix_counts: Dict[str, int] = {}
    for line in lines:
        if len(line) >= 2:
            prefix_counts[line[0:2]] = prefix_counts.get(line[0:2], 0) + 1
    dominant_prefix = (
        max(prefix_counts, key=lambda k: prefix_counts[k]) if prefix_counts else None
    )
    is_fixed_width = (
        not is_delimited
        and dominant_prefix is not None
        and prefix_counts.get(dominant_prefix, 0) >= len(lines) * 0.7
    )

    # measure where matched ref values start in each line
    ref_offsets: List[int] = []
    for rec in matched_records[:100]:
        for m in rec["matched"]:
            idx = rec["line"].find(m["value"])
            if idx >= 0:
                ref_offsets.append(idx)
    ref_offset_avg = int(sum(ref_offsets) / len(ref_offsets)) if ref_offsets else 0

    _FIELD_META = {
        "tx_id":        {"maps_to_camt": "Refs/EndToEndId",    "reason": "TX- prefix + 4-digit year + sequence number — highly specific, very low false-positive risk"},
        "reference":    {"maps_to_camt": "Ustrd (remittance)", "reason": "PMT-REF- prefix + numeric suffix — structured token, collision is extremely rare"},
        "invoice":      {"maps_to_camt": "Ustrd (remittance)", "reason": "INV- prefix + digits — specific but optional separator widens match surface slightly"},
        "amount":       {"maps_to_camt": "Amt",                "reason": "12-digit zero-padded integer anchored by CR/DR lookahead — positional and fully numeric"},
        "direction":    {"maps_to_camt": "CdtDbtInd",          "reason": "CR|DR are only 2 characters — may appear elsewhere in the line; relies on positional context to avoid false positives"},
        "booking_date": {"maps_to_camt": "BookgDt/Dt",         "reason": "8-digit YYYYMMDD immediately after the tx_id sequence number"},
        "counterparty": {"maps_to_camt": "RltdPties/Dbtr/Nm",  "reason": "free-text name field starting 25 chars after CR/DR — captures company name for fuzzy matching"},
    }

    def _enrich(regex_map: Dict[str, str]) -> Dict[str, object]:
        return {
            field: {"regex": pattern, **_FIELD_META.get(field, {"maps_to_camt": "", "confidence": "medium"})}
            for field, pattern in regex_map.items()
        }

    if is_fixed_width:
        regex_map = {
            # Greedy \d+ backtracks to stop before the 8-digit date (lazy caused truncation).
            "tx_id":        r"^.{2}(?P<tx_id>TX-\d{4}-\d+)(?=\d{8})",
            "booking_date": r"^.{2}TX-\d{4}-\d+(?P<booking_date>\d{8})",
            "reference":    r"(?P<reference>PMT-REF-\d+)",
            "invoice":      r"(?P<invoice>INV-?\d{4}-?\d+)",
            # 12-digit zero-padded amount immediately before CR/DR.
            "amount":       r"(?P<amount>\d{12})(?=CR|DR)",
            "direction":    r"(?P<direction>CR|DR)",
            # 25-char fixed-width invoice slot after CR/DR, then the counterparty name.
            "counterparty": r"(?:CR|DR).{25}\s*(?P<counterparty>[A-Za-z][A-Za-z0-9 ,\.&'\-/]+)",
        }
        return {
            "detected_type": "FIXED_WIDTH",
            "record_prefix": dominant_prefix,
            "delimiter": None,
            "field_positions": {
                "record_type": (0, 2),
                "ref_approx_start": ref_offset_avg,
            },
            "suggested_regex_map": regex_map,
            "structural_field_info": _enrich(regex_map),
            "sample_lines": sample_lines,
        }

    if is_delimited:
        regex_map = {
            "tx_id":     r"(?P<tx_id>TX-\d{4}-\d+)",
            "reference": r"(?P<reference>PMT-REF-\d+)",
            "invoice":   r"(?P<invoice>INV-?\d{4}-?\d+)",
            "amount":    r"(?P<amount>\d+(?:\.\d+)?)",
            "direction": r"(?P<direction>CR|DR)",
        }
        return {
            "detected_type": "DELIMITED",
            "record_prefix": None,
            "delimiter": dominant_delim,
            "field_positions": {},
            "suggested_regex_map": regex_map,
            "structural_field_info": _enrich(regex_map),
            "sample_lines": sample_lines,
        }

    return {
        "detected_type": "UNKNOWN",
        "record_prefix": dominant_prefix,
        "delimiter": None,
        "field_positions": {"ref_approx_start": ref_offset_avg},
        "suggested_regex_map": {},
        "structural_field_info": {},
        "sample_lines": sample_lines,
    }


def recognize_files(camt_upload: UploadFile, other_upload: UploadFile) -> Dict[str, object]:
    """Attempt to auto-recognize the uploaded CAMT file and the other file format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        camt_path = _write_upload_to_temp(camt_upload, temp_dir_path)
        other_path = _write_upload_to_temp(other_upload, temp_dir_path)

        try:
            camt_transactions = _load_camt(camt_path)
        except Exception as exc:
            raise ValueError(f"CAMT file parse failed: {exc}") from exc

        other_format_hint = _guess_format(other_path, other_upload.content_type)
        other_details: Dict[str, object] = {"format_hint": other_format_hint}

        if other_format_hint == "XML":
            try:
                xml_transactions = _load_camt(other_path)
                other_details["parsed_as"] = "CAMT"
                other_details["transaction_count"] = len(xml_transactions)
                other_details["parse_success"] = True
            except Exception:
                other_details["parsed_as"] = "UNKNOWN"
                other_details["transaction_count"] = 0
                other_details["parse_success"] = False
        elif other_format_hint == "TEXT":
            try:
                # Phase 1 — stream CAMT with iterparse, build identifier-only index.
                # Only <Refs> children + remittance PMT-REF/INV tokens are collected;
                # amounts, dates, and names are excluded to avoid false positives.
                value_to_entry, all_values = _build_camt_ref_index(camt_path)

                # Phase 2 — scan flat file line-by-line with a single combined regex.
                # The file is never fully loaded into memory.
                matched_records = _scan_flat_file_for_refs(
                    other_path, value_to_entry, all_values
                )

                # Phase 3 — derive the flat-file format from the matched dataset.
                format_info = _infer_flat_file_format(matched_records)

                # Count total lines without loading the whole file
                with other_path.open("r", encoding="utf-8", errors="replace") as _fh:
                    line_count = sum(1 for _ in _fh)

                # Attempt structured PSR parse for transaction count (best-effort)
                header, psr_transactions = parse_psr_file(other_path)

                other_details["camt_ref_index_size"] = len(all_values)
                other_details["psr_transaction_count"] = len(psr_transactions)
                other_details["parsed_as"] = "PSR" if psr_transactions else "TEXT"
                other_details["line_count"] = line_count
                other_details["match_count"] = len(matched_records)
                other_details["matches"] = [
                    {
                        "line_no": r["line_no"],
                        "line": r["line"].strip(),
                        "matched": [
                            {
                                "value": m["value"],
                                "camt_ref_tags": list(
                                    m["camt_entry"].get("refs", {}).keys()
                                ),
                            }
                            for m in r["matched"]
                        ],
                    }
                    for r in matched_records
                ]
                other_details["format_info"] = format_info
                other_details["ref_index_sample"] = list(all_values)[:10]
                other_details["parse_success"] = (
                    bool(psr_transactions) or len(matched_records) > 0
                )
            except Exception:
                logger.exception(
                    "TEXT branch recognition failed for %s", other_path
                )
                other_details["line_count"] = 0
                other_details["matches"] = []
                other_details["match_count"] = 0
                other_details["parse_success"] = False
        else:
            other_details["parse_success"] = False

        return {
            "camt": {
                "filename": camt_upload.filename,
                "content_type": camt_upload.content_type,
                "transaction_count": len(camt_transactions),
            },
            "other": {
                "filename": other_upload.filename,
                "content_type": other_upload.content_type,
                **other_details,
            },
            "recognized_type": other_format_hint,
        }


def _common_prefix(strings: List[str]) -> str:
    if not strings:
        return ""
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix


def _infer_reference_regex(samples: List[str]) -> str:
    values = [value for value in samples if value]
    if not values:
        return r".+?"
    if all(re.fullmatch(r"PMT-REF-\d+", value, re.IGNORECASE) for value in values):
        return r"PMT-REF-\d+"
    if all(re.fullmatch(r"TX-\d{4}-\d+", value, re.IGNORECASE) for value in values):
        return r"TX-\d{4}-\d+"
    if all(re.fullmatch(r"\d+", value) for value in values):
        return r"\d+"
    if all(re.fullmatch(r"[A-Z0-9-]+", value, re.IGNORECASE) for value in values):
        prefix = _common_prefix(values)
        if prefix and prefix.endswith("-") and len(prefix) >= 3:
            return re.escape(prefix) + r"\d+"
        return r"[A-Z0-9-]+"
    return r".+?"


def _field_match_summary(camt_transactions: List[CamtTransaction], psr_transactions: List[PsrTransaction]) -> Dict[str, object]:
    candidates = {
        "id": {"camt_field": "end_to_end_id", "psr_field": "id", "count": 0, "samples": []},
        "reference": {"camt_field": "pmt_ref", "psr_field": "reference", "count": 0, "samples": []},
        "invoice": {"camt_field": "invoice", "psr_field": "invoice", "count": 0, "samples": []},
    }
    camt_lookup = {key: {} for key in candidates}
    for camt in camt_transactions:
        for key, meta in candidates.items():
            value = getattr(camt, meta["camt_field"], "") or ""
            if value:
                camt_lookup[key].setdefault(value.strip().upper(), []).append(camt)
    for psr in psr_transactions:
        for key, meta in candidates.items():
            value = getattr(psr, meta["psr_field"], "") or ""
            if not value:
                continue
            normalized = value.strip().upper()
            if normalized in camt_lookup[key]:
                candidates[key]["count"] += 1
                if len(candidates[key]["samples"]) < 5:
                    candidates[key]["samples"].append(value)
    return candidates


def _select_best_mapping(summary: Dict[str, object]) -> Optional[Dict[str, object]]:
    ordered_keys = ["id", "reference", "invoice"]
    best_key = None
    best_count = -1
    for key in ordered_keys:
        count = summary[key]["count"]
        if count > best_count:
            best_count = count
            best_key = key
    if best_key is None or best_count <= 0:
        return None
    result = {**summary[best_key], "mapping_key": best_key}
    return result


def _build_reconciliation_pattern(
    camt_transactions: List[CamtTransaction],
    psr_transactions: List[PsrTransaction],
    provided_regex_map: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    summary = _field_match_summary(camt_transactions, psr_transactions)
    best_match = _select_best_mapping(summary)
    if best_match is None:
        raise ValueError("No exact unique identifier match could be found between PSR and CAMT transactions.")

    mapping_key = best_match["mapping_key"]
    if mapping_key == "id":
        camt_field = "end_to_end_id"
        psr_field = "id"
        pattern_name = "Auto-generated Exact EndToEndId Match"
    elif mapping_key == "reference":
        camt_field = "pmt_ref"
        psr_field = "reference"
        pattern_name = "Auto-generated Exact PMT-REF Match"
    else:
        camt_field = "invoice"
        psr_field = "invoice"
        pattern_name = "Auto-generated Exact Invoice Match"

    sample_values = [value for value in best_match.get("samples", []) if value]
    if not sample_values and psr_transactions:
        sample_values = [getattr(psr_transactions[0], psr_field, "") or ""]

    inferred_regex = _infer_reference_regex(sample_values)
    regex_map = provided_regex_map or {camt_field: inferred_regex}
    pattern_rule = {
        "fields": [camt_field],
        "mode": "AUTO",
        "regex_map": regex_map,
    }
    return {
        "mapping_key": mapping_key,
        "pattern_name": pattern_name,
        "pattern_rule": pattern_rule,
        "sample_values": sample_values,
        "regex_inferred": regex_map,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Two-phase reconciliation pattern discovery helpers
# ---------------------------------------------------------------------------

def _normalise_field_extractors(
    provided: Optional[Dict[str, object]],
) -> Optional[Dict[str, str]]:
    """Coerce several possible input shapes to a flat ``{field: regex_str}`` dict.

    Accepted shapes
    ---------------
    * LLM field_extractors:
      ``{"tx_id": {"regex": "...", "maps_to_camt": "...", ...}, ...}``
    * Structural suggested_regex_map:
      ``{"record_type": "^20", "ref_field": "...", ...}``
    * Old simple map:
      ``{"pmt_ref": "\\d+", ...}``
    * Wrapped in a ``field_extractors`` key:
      ``{"field_extractors": {...}, ...}``
    """
    if not provided:
        return None
    first_val = next(iter(provided.values()), None)
    if isinstance(first_val, dict) and "regex" in first_val:
        return {
            field: info["regex"]
            for field, info in provided.items()
            if isinstance(info, dict) and info.get("regex")
        }
    if "field_extractors" in provided:
        return _normalise_field_extractors(provided["field_extractors"])
    if all(isinstance(v, str) for v in provided.values()):
        return provided  # type: ignore[return-value]
    return None


def _parse_flat_file_with_extractors(
    path: Path,
    field_regexes: Dict[str, str],
    record_prefix: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Apply field-extractor regexes line-by-line; skip lines not starting with
    *record_prefix*.  Named capture groups are preferred over the whole match.
    """
    compiled: Dict[str, re.Pattern] = {}
    for field, pattern in field_regexes.items():
        try:
            compiled[field] = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            logger.warning("Skipping invalid regex for field %r: %s", field, exc)

    records: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if record_prefix and not line.startswith(record_prefix):
                continue
            record: Dict[str, str] = {"raw_line": line, "line_no": str(line_no)}
            for field, pat in compiled.items():
                m = pat.search(line)
                if m:
                    gd = m.groupdict()
                    record[field] = (
                        gd[field] if field in gd else
                        next(iter(gd.values()), m.group(0)) if gd else
                        m.group(0)
                    )
                else:
                    record[field] = ""
            records.append(record)
    return records


def _norm_amount(raw: str) -> str:
    """Strip leading zeros from a digit string for amount comparison."""
    s = (raw or "").strip()
    return str(int(s)) if s.isdigit() else s


def _norm_date(s: str) -> str:
    """Normalise YYYYMMDD or YYYY-MM-DD to YYYY-MM-DD for comparison."""
    s = (s or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _within_pct(a_norm: str, b_norm: str, pct: float) -> bool:
    """True if two normalised integer-string amounts are within pct of each other."""
    try:
        ai, bi = int(a_norm), int(b_norm)
        if ai == 0 and bi == 0:
            return True
        return abs(ai - bi) / max(abs(ai), abs(bi)) <= pct
    except (ValueError, TypeError):
        return False


_AMT_VARIANCE_PCT        = 0.02   # ±2 % for tier-5 variance rules
_AMT_FUZZY_PCT           = 0.005  # ±0.5 % for tier-4 fuzzy rule
_BATCH_MAX_N             = 5      # max PSR lines in one batch
_BATCH_GROUP_CAP         = 30     # skip subset-sum if candidate pool exceeds this
_COUNTERPARTY_THRESHOLD  = 85     # rapidfuzz token_set_ratio floor for P4 (0–100)
_SPLIT_MAX_N             = 5      # max CAMT entries in a split group (P10)


_DET_RULES = [
    # Tier 1 – reference ID + exact amount
    ("EXACT_E2E",                  "Exact EndToEndId Match",                   ["end_to_end_id", "amount"]),
    ("EXACT_PMT_REF",              "PMT-REF + Amount",                         ["pmt_ref", "amount"]),
    ("EXACT_INVOICE",              "Invoice Extracted from Ustrd",             ["invoice", "amount"]),
    # Tier 2 – batch (N PSR → 1 CAMT); runs early to avoid starving batch groups
    ("BATCH_SUM",                  "One-to-Many Bank Settlement",              ["amount"]),
    ("BATCH_SUM_VAR",              "One-to-Many Settlement (Amount Variance)", ["amount"]),
    # Tier 3 – identity-anchored amount variance ±0.5 % (≡ P7 minor)
    ("FUZZY_AMT_DIR",              "Amount Variance",                          ["amount", "direction"]),
    # Tier 4 – identity-anchored amount variance ±2 %
    ("APPROX_E2E_VAR",             "Amount Variance – EndToEndId",             ["end_to_end_id", "amount"]),
    ("APPROX_PMT_REF_VAR",         "Amount Variance – PMT-REF",               ["pmt_ref", "amount"]),
    ("APPROX_INVOICE_VAR",         "Amount Variance – Invoice",               ["invoice", "amount"]),
    # Tier 5 – counterparty fuzzy match (P4); before date/ccy so P4 wins
    ("FUZZY_COUNTERPARTY",         "Counterparty Fuzzy Match",                 ["counterparty", "amount"]),
    # Tier 6 – financial attributes only (no identity, no counterparty match)
    ("EXACT_AMT_DATE_CCY",         "Exact Amount + Date + Currency",           ["amount", "booking_date", "currency"]),
    ("APPROX_AMT_DATE_VAR",        "Amount Variance – Date + Currency",        ["amount", "booking_date", "currency"]),
    # Tier 7 – post-pass: 1 PSR → N CAMT split settlement (P10)
    ("SPLIT_SETTLEMENT",           "Split Settlement (1 PSR -> N CAMTs)",      ["pmt_ref", "amount_sum"]),
    ("SPLIT_SETTLEMENT_MINOR_VAR", "Split Settlement – Minor Variance",        ["pmt_ref", "amount_sum"]),
    ("SPLIT_SETTLEMENT_MAJOR_VAR", "Split Settlement – Major Variance",        ["pmt_ref", "amount_sum"]),
    # Remainder → exception queue (unmatched_camt return value)
]

# Maps each discovery rule → the seed pattern it confirms or is closest to.
# None means the rule covers a scenario not yet represented in the seed registry.
_DET_RULE_SEED: Dict[str, Optional[str]] = {
    "EXACT_E2E":                  "P1",
    "EXACT_PMT_REF":              "P2",
    "EXACT_INVOICE":              "P3",
    "BATCH_SUM":                  "P6",
    "BATCH_SUM_VAR":              "P6",
    "EXACT_AMT_DATE_CCY":         "P8",
    "FUZZY_AMT_DIR":              "P7",
    "APPROX_E2E_VAR":             "P7",
    "APPROX_PMT_REF_VAR":         "P7",
    "APPROX_INVOICE_VAR":         "P7",
    "APPROX_AMT_DATE_VAR":        None,
    "FUZZY_COUNTERPARTY":         "P4",
    "SPLIT_SETTLEMENT":           "P10",
    "SPLIT_SETTLEMENT_MINOR_VAR": "P10",
    "SPLIT_SETTLEMENT_MAJOR_VAR": "P10",
}


def _run_deterministic_matching(
    camt_transactions: List[CamtTransaction],
    flat_records: List[Dict[str, str]],
) -> Dict[str, object]:
    """Six-tier deterministic cascade; each side consumed at most once.

    Tiers: 1=Exact ID+Amount  2=Amt+Date+Ccy  3=Batch Sum
           4=Fuzzy Amt(±0.5%)  5=Variance variants(±2%)  6→exception queue
    """
    # --- static indexes (built once) ---
    flat_by: Dict[str, Dict[str, Dict]] = {k: {} for k in ("tx_id", "reference", "invoice")}
    flat_by_amount: Dict[str, List[Dict]] = {}
    flat_by_amt_date_ccy: Dict[tuple, List[Dict]] = {}

    for rec in flat_records:
        for field in ("tx_id", "reference", "invoice"):
            val = rec.get(field, "").strip().upper()
            if val and val not in flat_by[field]:
                flat_by[field][val] = rec
        amt  = _norm_amount(rec.get("amount", ""))
        date = _norm_date(rec.get("booking_date", ""))
        ccy  = (rec.get("currency", "") or "").strip().upper()
        if amt:
            flat_by_amount.setdefault(amt, []).append(rec)
            flat_by_amt_date_ccy.setdefault((amt, date, ccy), []).append(rec)

    consumed_flat: set = set()
    consumed_camt: set = set()
    stats_map: Dict[str, Dict] = {
        rid: {"rule": rid, "pattern_name": name, "fields_used": fields,
              "seed_pattern_id": _DET_RULE_SEED.get(rid),
              "matched_count": 0, "sample_pairs": []}
        for rid, name, fields in _DET_RULES
    }
    all_pairs: List[Dict] = []

    def _unconsumed(field_dict: Dict, key: str) -> Optional[Dict]:
        r = field_dict.get(key)
        return r if r and r["line_no"] not in consumed_flat else None

    def _find_batch(target_norm: str, candidates: List[Dict]) -> Optional[List[Dict]]:
        avail = [r for r in candidates if r["line_no"] not in consumed_flat]
        if len(avail) < 2 or len(avail) > _BATCH_GROUP_CAP or not target_norm.isdigit():
            return None
        target = int(target_norm)
        for n in range(2, min(_BATCH_MAX_N + 1, len(avail) + 1)):
            for combo in itertools.combinations(avail, n):
                total = sum(int(_norm_amount(r.get("amount", "0")) or "0") for r in combo)
                if total == target:
                    return list(combo)
        return None

    def _find_batch_approx(target_norm: str, candidates: List[Dict], tol: float) -> Optional[List[Dict]]:
        avail = [r for r in candidates if r["line_no"] not in consumed_flat]
        if len(avail) < 2 or len(avail) > _BATCH_GROUP_CAP or not target_norm.isdigit():
            return None
        target = int(target_norm)
        for n in range(2, min(_BATCH_MAX_N + 1, len(avail) + 1)):
            for combo in itertools.combinations(avail, n):
                total = sum(int(_norm_amount(r.get("amount", "0")) or "0") for r in combo)
                if abs(total - target) <= tol:
                    return list(combo)
        return None

    def _record_match(rule: str, camt: CamtTransaction, recs: List[Dict]) -> None:
        consumed_camt.add(camt.ntry_id)
        for r in recs:
            consumed_flat.add(r["line_no"])
        is_batch = len(recs) > 1
        pair = {
            "camt_id": camt.camt_id,
            "camt_amount": camt.amount, "camt_currency": camt.currency,
            "camt_direction": camt.direction,
            "camt_counterparty": camt.counterparty,
            "flat_line_no":  recs[0].get("line_no") if not is_batch else None,
            "flat_line_nos": [r.get("line_no") for r in recs] if is_batch else None,
            "flat_tx_id":    recs[0].get("tx_id", "") if not is_batch else "",
            "flat_reference": recs[0].get("reference", "") if not is_batch else "",
            "flat_amount": (recs[0].get("amount", "") if not is_batch
                            else str(sum(int(_norm_amount(r.get("amount", "0")) or "0") for r in recs))),
            "flat_direction": recs[0].get("direction", ""),
            "batch_size": len(recs),
            "rule": rule,
        }
        all_pairs.append(pair)
        bucket = stats_map[rule]
        bucket["matched_count"] += 1
        if len(bucket["sample_pairs"]) < 3:
            bucket["sample_pairs"].append(pair)

    for camt in camt_transactions:
        if camt.ntry_id in consumed_camt:
            continue

        camt_amt = _norm_amount(str(int(camt.amount)) if camt.amount else "")
        cdir  = (camt.direction or "").strip().upper()
        cdate = _norm_date(camt.booking_date or camt.value_date or "")
        cccy  = (camt.currency or "").strip().upper()
        e2e   = (camt.end_to_end_id or "").strip().upper()
        ref   = (camt.pmt_ref or "").strip().upper()
        inv   = (camt.invoice or "").strip().upper()
        matched_rule: Optional[str] = None
        matched_recs: Optional[List[Dict]] = None

        # ── Tier 1: reference ID + exact amount ────────────────────────────
        if e2e:
            r = _unconsumed(flat_by["tx_id"], e2e)
            if r and _norm_amount(r.get("amount", "")) == camt_amt:
                matched_rule, matched_recs = "EXACT_E2E", [r]

        if not matched_rule and ref:
            r = _unconsumed(flat_by["reference"], ref)
            if r and _norm_amount(r.get("amount", "")) == camt_amt:
                matched_rule, matched_recs = "EXACT_PMT_REF", [r]

        if not matched_rule and inv:
            r = _unconsumed(flat_by["invoice"], inv)
            if r and _norm_amount(r.get("amount", "")) == camt_amt:
                matched_rule, matched_recs = "EXACT_INVOICE", [r]
            if not matched_rule:
                suf = invoice_suffix(inv)
                if suf:
                    for k, r2 in flat_by["invoice"].items():
                        if (invoice_suffix(k) == suf
                                and r2["line_no"] not in consumed_flat
                                and _norm_amount(r2.get("amount", "")) == camt_amt):
                            matched_rule, matched_recs = "EXACT_INVOICE", [r2]
                            break

        # Cross-field: CAMT e2e may live in PSR reference slot and vice-versa
        if not matched_rule and e2e:
            r = _unconsumed(flat_by["reference"], e2e)
            if r and _norm_amount(r.get("amount", "")) == camt_amt:
                matched_rule, matched_recs = "EXACT_E2E", [r]
        if not matched_rule and ref:
            r = _unconsumed(flat_by["tx_id"], ref)
            if r and _norm_amount(r.get("amount", "")) == camt_amt:
                matched_rule, matched_recs = "EXACT_PMT_REF", [r]

        # ── Tier 2: batch sum – extract ALL refs/invoices from remittance ────
        # Runs before EXACT_AMT_DATE_CCY so batch groups are not starved by
        # an unrelated PSR that happens to share amount+date.
        if not matched_rule and camt_amt:
            all_refs = {m.upper() for m in PMT_REF_RE.findall(camt.remittance or "")}
            all_invs = {
                m.group(0).upper().replace(" ", "-")
                for m in INVOICE_RE.finditer(camt.remittance or "")
            }
            ref_set = all_refs | all_invs
            if ref_set:
                batch_cands = [
                    r for r in flat_records
                    if r["line_no"] not in consumed_flat
                    and (not cdir or (r.get("direction", "") or "").strip().upper() == cdir)
                    and (
                        (r.get("reference", "") or "").strip().upper() in ref_set
                        or (r.get("invoice", "") or "").strip().upper() in ref_set
                    )
                ]
                batch = _find_batch(camt_amt, batch_cands)
                if batch:
                    matched_rule, matched_recs = "BATCH_SUM", batch
                else:
                    batch_var = _find_batch_approx(
                        camt_amt, batch_cands, settings.minor_variance_tolerance * 4
                    )
                    if batch_var:
                        matched_rule, matched_recs = "BATCH_SUM_VAR", batch_var

        # ── Tier 3: identity-anchored amount variance ±0.5 % (≡ P7 minor) ──
        # Only fires when an ID field points to a known PSR but amounts differ
        # slightly — keeps unanchored entries available for P4 (counterparty).
        if not matched_rule:
            for _field, _key in (("tx_id", e2e), ("reference", ref), ("invoice", inv)):
                if not _key:
                    continue
                r = flat_by[_field].get(_key)
                if r and r["line_no"] not in consumed_flat:
                    if _within_pct(camt_amt, _norm_amount(r.get("amount", "")), _AMT_FUZZY_PCT):
                        matched_rule, matched_recs = "FUZZY_AMT_DIR", [r]
                        break

        # ── Tier 4: identity-anchored amount variance ±2 % ─────────────────
        if not matched_rule and e2e:
            r = _unconsumed(flat_by["tx_id"], e2e)
            if r and _within_pct(camt_amt, _norm_amount(r.get("amount", "")), _AMT_VARIANCE_PCT):
                matched_rule, matched_recs = "APPROX_E2E_VAR", [r]

        if not matched_rule and ref:
            r = _unconsumed(flat_by["reference"], ref)
            if r and _within_pct(camt_amt, _norm_amount(r.get("amount", "")), _AMT_VARIANCE_PCT):
                matched_rule, matched_recs = "APPROX_PMT_REF_VAR", [r]

        if not matched_rule and inv:
            r = _unconsumed(flat_by["invoice"], inv)
            if r and _within_pct(camt_amt, _norm_amount(r.get("amount", "")), _AMT_VARIANCE_PCT):
                matched_rule, matched_recs = "APPROX_INVOICE_VAR", [r]

        # ── Tier 5: counterparty fuzzy match (P4) ──────────────────────────
        # Runs before EXACT_AMT_DATE_CCY so counterparty-confirmed pairs are
        # not stolen by a same-amount PSR with a different counterparty.
        if not matched_rule and camt_amt and camt.counterparty and _fuzz:
            cparty = (camt.counterparty or "").strip()
            for r in flat_records:
                if r["line_no"] in consumed_flat:
                    continue
                if _norm_amount(r.get("amount", "")) != camt_amt:
                    continue
                rcparty = (r.get("counterparty", "") or "").strip()
                if not rcparty:
                    continue
                if _fuzz.token_set_ratio(cparty, rcparty) >= _COUNTERPARTY_THRESHOLD:
                    matched_rule, matched_recs = "FUZZY_COUNTERPARTY", [r]
                    break

        # ── Tier 6: exact amount + date + currency ───────────────────────
        if not matched_rule and camt_amt and cdate:
            for key in ((camt_amt, cdate, cccy), (camt_amt, cdate, "")):
                for r in flat_by_amt_date_ccy.get(key, []):
                    if r["line_no"] not in consumed_flat:
                        matched_rule, matched_recs = "EXACT_AMT_DATE_CCY", [r]
                        break
                if matched_rule:
                    break

        if not matched_rule and camt_amt and cdate:
            for r in flat_records:
                if r["line_no"] in consumed_flat:
                    continue
                rdate = _norm_date(r.get("booking_date", ""))
                rccy  = (r.get("currency", "") or "").strip().upper()
                if rdate != cdate:
                    continue
                if cccy and rccy and cccy != rccy:
                    continue
                if _within_pct(camt_amt, _norm_amount(r.get("amount", "")), _AMT_VARIANCE_PCT):
                    matched_rule, matched_recs = "APPROX_AMT_DATE_VAR", [r]
                    break

        if matched_rule and matched_recs:
            _record_match(matched_rule, camt, matched_recs)

    # ── SPLIT_SETTLEMENT post-pass: 1 PSR → N CAMTs (P10) ───────────────────
    # Group remaining unmatched CAMTs by shared pmt_ref (or invoice fallback)
    split_groups: Dict[str, list] = {}
    for c in camt_transactions:
        if c.ntry_id in consumed_camt:
            continue
        key = (c.pmt_ref or c.invoice or "").strip().upper()
        if key:
            split_groups.setdefault(key, []).append(c)

    for key, group in split_groups.items():
        if len(group) < 2 or len(group) > _SPLIT_MAX_N:
            continue
        dirs = {(c.direction or "").strip().upper() for c in group}
        if len(dirs) > 1:
            continue
        group_dir = next(iter(dirs), "")
        group_amt_int = sum(
            int(_norm_amount(str(int(c.amount)) if c.amount else "0") or "0")
            for c in group
        )
        minor_tol = settings.minor_variance_tolerance
        for r in flat_records:
            if r["line_no"] in consumed_flat:
                continue
            rdir = (r.get("direction", "") or "").strip().upper()
            if group_dir and rdir and rdir != group_dir:
                continue
            try:
                r_amt_int = int(_norm_amount(r.get("amount", "")) or "0")
            except ValueError:
                continue
            diff = abs(group_amt_int - r_amt_int)
            if diff == 0:
                split_rule = "SPLIT_SETTLEMENT"
            elif diff <= minor_tol:
                split_rule = "SPLIT_SETTLEMENT_MINOR_VAR"
            elif diff <= minor_tol * 4:
                split_rule = "SPLIT_SETTLEMENT_MAJOR_VAR"
            else:
                continue
            for c in group:
                consumed_camt.add(c.ntry_id)
            consumed_flat.add(r["line_no"])
            pair = {
                "camt_ids":      [c.ntry_id for c in group],
                "camt_amounts":  [c.amount for c in group],
                "camt_total":    sum(c.amount for c in group if c.amount),
                "camt_currency": group[0].currency,
                "camt_direction": group_dir,
                "flat_line_no":  r.get("line_no"),
                "flat_amount":   r.get("amount", ""),
                "flat_reference": r.get("reference", "") or key,
                "split_size":    len(group),
                "batch_size":    1,
                "rule":          split_rule,
            }
            all_pairs.append(pair)
            bucket = stats_map[split_rule]
            bucket["matched_count"] += 1
            if len(bucket["sample_pairs"]) < 3:
                bucket["sample_pairs"].append(pair)
            break

    unmatched_camt = [c for c in camt_transactions if c.camt_id not in consumed_camt]
    unmatched_flat = [r for r in flat_records if r["line_no"] not in consumed_flat]
    return {
        "patterns": [p for p in stats_map.values() if p["matched_count"] > 0],
        "all_rules": list(stats_map.values()),
        "matched_pairs": all_pairs,
        "unmatched_camt": unmatched_camt,
        "unmatched_flat": unmatched_flat,
        "stats": {
            "camt_total": len(camt_transactions),
            "flat_total": len(flat_records),
            "camt_matched": len(consumed_camt),
            "camt_unmatched": len(unmatched_camt),
            "flat_matched": len(consumed_flat),
            "flat_unmatched": len(unmatched_flat),
            "match_rate": round(len(consumed_camt) / max(len(camt_transactions), 1), 4),
        },
    }


def _build_unmatched_pattern_prompt(
    unmatched_camt: List[CamtTransaction],
    unmatched_flat: List[Dict[str, str]],
    max_samples: int = 6,
) -> str:
    """Build LLM prompt asking for fuzzy / tolerance-based patterns for the
    CAMT entries that could not be matched deterministically.
    """
    camt_block = "\n".join(
        f"  id={c.camt_id}  amount={c.amount} {c.currency}  dir={c.direction}  "
        f"date={c.booking_date}  party={c.counterparty!r}  "
        f"ref={c.pmt_ref}  inv={c.invoice}  remit={c.remittance!r}"
        for c in unmatched_camt[:max_samples]
    ) or "  (none)"

    flat_block = "\n".join(
        "  line {ln}: {fields}  raw: {raw}".format(
            ln=r.get("line_no"),
            fields={k: v for k, v in r.items() if k not in ("raw_line", "line_no") and v},
            raw=(r.get("raw_line") or "")[:80],
        )
        for r in unmatched_flat[:max_samples]
    ) or "  (none)"

    return (
        "You are an expert payment reconciliation analyst.\n\n"
        "The following CAMT.053 entries could NOT be matched to any internal payment "
        "record using the full deterministic cascade (Exact ID+Amount, Exact Amt+Date+Ccy, "
        "One-to-Many Batch, Amount Variance ±0.5%, Variance ±2%, Counterparty Fuzzy, "
        "Split Settlement).\n\n"
        f"Unmatched CAMT entries ({len(unmatched_camt)} total, showing ≤{max_samples}):\n"
        f"{camt_block}\n\n"
        f"Unmatched flat-file records ({len(unmatched_flat)} total, showing ≤{max_samples}):\n"
        f"{flat_block}\n\n"
        "Propose a prioritised list of ADDITIONAL reconciliation patterns.\n"
        "Focus on tolerance / fuzzy techniques such as:\n"
        "  - Amount variance (e.g. ±0.5% or ±1 currency unit)\n"
        "  - Date tolerance (booking_date within ±2 business days)\n"
        "  - Counterparty name similarity (token-set ratio ≥ 85%)\n"
        "  - Partial reference match (common suffix or numeric tail)\n"
        "  - Combined scoring (amount exact + counterparty ≥ 70%)\n\n"
        "Return ONLY valid JSON — no markdown:\n"
        "{\n"
        '  "patterns": [\n'
        "    {\n"
        '      "rule_id": "AMOUNT_VARIANCE",\n'
        '      "pattern_name": "Amount Variance ±0.5%",\n'
        '      "description": "...",\n'
        '      "fields_used": ["amount", "direction"],\n'
        '      "tolerance_spec": {"amount_pct": 0.5},\n'
        '      "estimated_coverage": "high|medium|low",\n'
        '      "confidence": "high|medium|low"\n'
        "    }\n"
        "  ],\n"
        '  "explanation": "Why these patterns and what in the data suggested them."\n'
        "}\n"
    )


def generate_reconciliation_patterns(
    camt_path: Path,
    other_path: Path,
    provided_regex_map: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Two-phase reconciliation pattern discovery.

    Phase 1 — Deterministic (12-rule cascade)
        Tier 1: Exact reference ID + amount (E2E, PMT-REF, Invoice)
        Tier 2: Exact Amount + Date + Currency
        Tier 3: Aggregated batch (N PSR → 1 CAMT, One-to-Many Settlement)
        Tier 4: Amount Variance ±0.5% + direction
        Tier 5: Variance variants ±2% (ID-anchored + date/ccy)
        Tier 5b: Counterparty Fuzzy Match (≥85%)
        Tier 6: Split Settlement post-pass (1 PSR → N CAMTs)

    Phase 2 — LLM-assisted
        For CAMT entries not matched by any deterministic rule, ask the LLM
        to propose additional tolerance / fuzzy patterns.
    """
    camt_transactions = _load_camt(camt_path)
    field_regexes = _normalise_field_extractors(provided_regex_map)

    # ── Phase 1: parse flat file ─────────────────────────────────────
    if field_regexes:
        record_prefix: Optional[str] = None
        if isinstance(provided_regex_map, dict):
            fmt = (provided_regex_map.get("format_info") or {})
            record_prefix = fmt.get("record_prefix") or None
        flat_records = _parse_flat_file_with_extractors(
            other_path, field_regexes, record_prefix=record_prefix or "20"
        )
        if not flat_records:
            raise ValueError(
                "No records matched the provided regex patterns in the flat file."
            )
    else:
        _, psr_transactions = parse_psr_file(other_path)
        if not psr_transactions:
            raise ValueError(
                "Uploaded file could not be parsed as a PSR file. "
                "Run \"Generate regex mapping\" first and pass the field extractors here."
            )
        flat_records = [
            {
                "raw_line": t.raw_line, "line_no": str(t.source_line),
                "tx_id": t.id, "reference": t.reference,
                "invoice": t.invoice,
                "amount": _norm_amount(str(int(t.amount)) if t.amount else ""),
                "direction": t.direction, "booking_date": t.execution_date,
                "currency": t.currency, "counterparty": t.counterparty,
            }
            for t in psr_transactions
        ]

    det = _run_deterministic_matching(camt_transactions, flat_records)

    # ── Phase 2: LLM for unmatched ───────────────────────────────────
    unmatched_camt: List[CamtTransaction] = det["unmatched_camt"]
    unmatched_flat: List[Dict] = det["unmatched_flat"]

    logger.info(
        "[reconcile-patterns] det complete — matched=%d unmatched_camt=%d unmatched_flat=%d",
        det["stats"]["camt_matched"], len(unmatched_camt), len(unmatched_flat),
    )
    for p in det["patterns"]:
        logger.info("  det pattern: %-20s  matches=%d", p["rule"], p["matched_count"])

    llm_result: Dict[str, object] = {"llm_available": False}
    if unmatched_camt or unmatched_flat:
        prompt = _build_unmatched_pattern_prompt(unmatched_camt, unmatched_flat)
        llm_result["prompt"] = prompt
        try:
            out = _llm_json_completion(prompt)
            llm_result["llm_available"] = True
            llm_result["llm_patterns"] = out.get("patterns", [])
            llm_result["llm_explanation"] = out.get("explanation", "")
            logger.info(
                "[reconcile-patterns] LLM returned %d pattern(s): %s",
                len(llm_result["llm_patterns"]),
                [p.get("rule_id") for p in llm_result["llm_patterns"]],
            )
            logger.info("[reconcile-patterns] LLM explanation: %s", llm_result["llm_explanation"])
            logger.debug("[reconcile-patterns] LLM raw output: %s", out)
        except ValueError as exc:
            logger.warning("[reconcile-patterns] LLM error: %s", exc)
            llm_result["llm_error"] = str(exc)
        except Exception as exc:
            logger.warning("[reconcile-patterns] LLM error: %s", exc)
            llm_result["llm_error"] = str(exc)
    else:
        llm_result["llm_patterns"] = []
        llm_result["llm_explanation"] = (
            "All entries matched deterministically — no LLM pass needed."
        )
        logger.info("[reconcile-patterns] skipping LLM — all entries matched deterministically")

    return {
        "deterministic_patterns": det["patterns"],
        "all_deterministic_rules": det["all_rules"],
        "matched_pairs_sample": det["matched_pairs"][:20],
        "unmatched_count": len(unmatched_camt),
        "unmatched_samples": [
            {
                "camt_id": c.camt_id, "amount": c.amount, "currency": c.currency,
                "direction": c.direction, "booking_date": c.booking_date,
                "counterparty": c.counterparty, "pmt_ref": c.pmt_ref,
                "invoice": c.invoice, "remittance": c.remittance,
            }
            for c in unmatched_camt[:8]
        ],
        "stats": det["stats"],
        **llm_result,
    }


def _build_regex_prompt(samples: List[Dict[str, object]]) -> str:
    """Build an LLM prompt from CAMT/flat-file matched pair samples.

    Each sample in *samples* is an entry dict from ``_build_camt_ref_index``
    with the shape::

        {
            ntry_ref, amount, currency, direction, booking_date,
            counterparty, remittance,
            refs: Dict[str, str],   # XML tag -> single identifier value
            pmt_ref, invoice,
            matched_text: List[str],  # raw flat-file lines that matched
        }

    The prompt shows each CAMT entry alongside its matched flat-file lines,
    annotated with the character offsets of the known identifier values, and
    asks the LLM to produce a JSON field-extractor schema for the flat file.
    """
    pair_blocks: List[str] = []
    for i, sample in enumerate(samples, start=1):
        # --- CAMT entry block ---
        camt_lines = [f"  CAMT entry {i}:"]
        camt_lines.append(f"    ntry_ref:     {sample.get('ntry_ref', '')}")
        refs: Dict[str, str] = sample.get("refs", {}) or {}
        for tag, val in refs.items():
            camt_lines.append(f"    {tag}: {val}")
        if sample.get("pmt_ref"):
            camt_lines.append(f"    pmt_ref:      {sample['pmt_ref']}")
        if sample.get("invoice"):
            camt_lines.append(f"    invoice:      {sample['invoice']}")
        camt_lines.append(
            f"    amount:       {sample.get('amount', '')} {sample.get('currency', '')}"
        )
        camt_lines.append(f"    direction:    {sample.get('direction', '')}")
        camt_lines.append(f"    booking_date: {sample.get('booking_date', '')}")
        camt_lines.append(f"    counterparty: {sample.get('counterparty', '')}")
        camt_lines.append(f"    remittance:   {sample.get('remittance', '')}")

        # --- matched flat-file lines, annotated with known-value offsets ---
        matched: List[str] = sample.get("matched_text", []) or []
        flat_lines = ["  Matched flat-file line(s):"]
        if matched:
            all_ids = list(refs.values()) + [
                v for v in (sample.get("pmt_ref"), sample.get("invoice")) if v
            ]
            for flat_line in matched:
                offsets = []
                for val in all_ids:
                    idx = flat_line.find(val) if val else -1
                    if idx >= 0:
                        offsets.append(f"'{val}' at offset {idx}")
                annotation = f"  [known: {', '.join(offsets)}]" if offsets else ""
                flat_lines.append(f"    {flat_line}{annotation}")
        else:
            flat_lines.append(
                "    (no matching flat-file line — patterns must be inferred "
                "from remittance text only)"
            )

        pair_blocks.append("\n".join(camt_lines) + "\n" + "\n".join(flat_lines))

    prompt = (
        "You are an expert at payment file reconciliation.\n\n"
        "You are given CAMT.053 bank statement entries paired with the flat-file "
        "(PSR / text) transaction lines that correspond to them.  The pairs were "
        "identified because known CAMT identifier values (EndToEndId, InstrId, "
        "PMT-REF numbers, INV numbers etc.) were found verbatim inside those "
        "flat-file lines.  Character offsets of the matching values are shown in "
        "square brackets to help you locate field boundaries.\n\n"
        "YOUR TASK:\n"
        "Analyse the CAMT field values and the structure of the matched flat-file "
        "lines, then produce a JSON extraction schema that can parse ANY line from "
        "this flat file to extract the fields needed for reconciliation.\n\n"
        "Use the known CAMT values (and their offsets) as anchors to infer the "
        "positions and patterns of surrounding fields.\n\n"
        "Required output — return ONLY valid JSON, no markdown:\n"
        "{\n"
        '  "format_type": "FIXED_WIDTH" | "DELIMITED" | "UNKNOWN",\n'
        '  "record_type_prefix": "20" | null,\n'
        '  "delimiter": null | "," | "\\t" | "|",\n'
        '  "field_extractors": {\n'
        '    "tx_id":        {"regex": "...", "maps_to_camt": "end_to_end_id or ntry_ref", "confidence": "high|medium|low"},\n'
        '    "reference":    {"regex": "...", "maps_to_camt": "pmt_ref",                   "confidence": "..."},\n'
        '    "invoice":      {"regex": "...", "maps_to_camt": "invoice",                   "confidence": "..."},\n'
        '    "amount":       {"regex": "...", "maps_to_camt": "amount",                    "confidence": "..."},\n'
        '    "direction":    {"regex": "...", "maps_to_camt": "direction",                 "confidence": "..."},\n'
        '    "booking_date": {"regex": "...", "maps_to_camt": "booking_date",              "confidence": "..."},\n'
        '    "counterparty": {"regex": "...", "maps_to_camt": "counterparty",              "confidence": "..."}\n'
        "  },\n"
        '  "explanation": "brief description of the detected layout"\n'
        "}\n\n"
        "Rules:\n"
        "- Use named capture groups in every regex, e.g. (?P<amount>\\d+).\n"
        "- For FIXED_WIDTH layouts, anchor patterns with positional ^ offsets "
        "where possible.\n"
        "- For entries with no matched flat-file line, base patterns solely on "
        "remittance text clues.\n"
        "- Do NOT guess fields that cannot be reliably identified — set confidence "
        "\"low\" and use a broad fallback regex instead.\n\n"
        "Entry pairs:\n\n"
        + "\n\n".join(pair_blocks)
    )
    return prompt


def _llm_json_completion(prompt: str) -> Dict[str, object]:
    import os
    from .config import settings

    provider = settings.llm_provider
    model = settings.llm_model
    max_tok = settings.llm_max_tokens

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Anthropic API key not configured")
        import anthropic as _anthropic
        _anthropic_client = _anthropic.Anthropic(api_key=api_key)
        response = _anthropic_client.messages.create(
            model=model,
            system="You are a JSON-only extraction assistant.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=max_tok,
        )
        raw_content = response.content[0].text
    else:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OpenRouter API key not configured")
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a JSON-only extraction assistant."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=max_tok,
        )
        raw_content = response.choices[0].message.content

    import json
    try:
        return json.loads(raw_content)
    except Exception:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_content.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)



def compare_patterns_with_llm(
    identified: List[Dict[str, object]],
    group_patterns: List[Dict[str, object]],
    group_name: str,
) -> Dict[str, object]:
    """Use the LLM to compare newly identified patterns against a saved group.

    Returns a dict with a *comparisons* list (one entry per identified pattern)
    and a short *summary* sentence.  Falls back to a field-only diff if the LLM
    is unavailable.
    """
    import json as _json

    def _fields(p: Dict) -> List[str]:
        rule = p.get("pattern_rule") or {}
        if isinstance(rule, str):
            try:
                rule = _json.loads(rule)
            except Exception:
                rule = {}
        return rule.get("fields") or []

    def _fmt(p: Dict, include_id: bool = False) -> str:
        pid = f"[{p['pattern_id']}] " if include_id and p.get("pattern_id") else ""
        fields = _fields(p)
        conf = int(float(p.get("confidence_threshold", 0.8)) * 100)
        mode = p.get("execution_mode", "SUGGESTION")
        return f"{pid}{p['pattern_name']}: fields={fields}, mode={mode}, confidence={conf}%"

    identified_block = "\n".join(f"  - {_fmt(p)}" for p in identified) or "  (none)"
    group_block = "\n".join(f"  - {_fmt(p, include_id=True)}" for p in group_patterns) or "  (none)"

    prompt = (
        "You are an expert payment reconciliation engineer.\n\n"
        "DOMAIN CONTEXT — fields available for matching:\n"
        "  PSR (internal payment settlement record) fields:\n"
        "    end_to_end_id  – unique transaction identifier; strongest match key when present\n"
        "    pmt_ref        – payment reference string; highly reliable when unique per payment\n"
        "    invoice        – invoice number extracted from remittance; reliable when structured\n"
        "    amount         – settlement amount; use only alongside a reference field to avoid collisions\n"
        "    direction      – CR or DR; adds safety when pairing amount-only rules\n"
        "    counterparty   – payer/payee name; fuzzy-match only, high false-positive risk alone\n"
        "    amount_sum     – sum of a group of PSR amounts; used in batch/split settlement patterns\n"
        "    amount_variance– tolerance band around amount; used for minor rounding or FX patterns\n"
        "  CAMT.053 (bank statement) fields: same set above, sourced from the bank entry.\n\n"
        "FIELD TAXONOMY:\n"
        "  Primary-key fields (drive pattern identity — what makes a payment unique):\n"
        "    end_to_end_id, pmt_ref, invoice, counterparty, amount_sum\n"
        "  Qualifier fields (guards/constraints, NOT primary identifiers):\n"
        "    amount, direction, amount_variance\n"
        "  CRITICAL: Two patterns that share ONLY qualifier fields (e.g. both use 'amount')\n"
        "  with NO shared primary-key field are NOVEL to each other — they match completely\n"
        "  different payment scenarios. Do NOT classify them as partial_overlap.\n"
        "  Example: [amount, direction] vs [counterparty, amount] → novel (no shared PK field).\n\n"
        "RECONCILIATION PRECISION RULE:\n"
        "  More matching fields = higher precision = fewer false positives = PREFERRED.\n"
        "  A pattern that uses [pmt_ref, amount] is BETTER than one using [pmt_ref] alone —\n"
        "  it adds the amount guard to prevent reference collisions.\n"
        "  A pattern using fewer fields than an existing one is RISKIER, not simpler.\n\n"
        f"Newly identified patterns (from file analysis):\n{identified_block}\n\n"
        f"Existing active patterns in group \"{group_name}\":\n{group_block}\n\n"
        "For each identified pattern, determine its relationship to the existing group.\n"
        "Consider the SEMANTIC role of each field, not just field count:\n"
        "  - Is the identified pattern a LOOSER version (fewer fields → higher false-positive risk)?\n"
        "  - Is it STRICTER (more fields → stronger precision, lower false-positive risk)?\n"
        "  - Does it cover a genuinely different matching scenario (different primary key field)?\n"
        "  - Would adding it alongside existing patterns create redundancy or useful extra precision?\n\n"
        "Recommendation guidance:\n"
        "  exact_match       → skip (duplicate)\n"
        "  stricter_superset → add  (more fields = higher precision, strengthens the group)\n"
        "  looser_subset     → review (fewer fields = more false positives; check if existing stricter rule is sufficient)\n"
        "  partial_overlap   → review (overlapping but divergent; assess whether both are needed)\n"
        "  novel             → add  (covers a new matching scenario)\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "comparisons": [\n'
        "    {\n"
        '      "identified_name": "<exact name from identified list>",\n'
        '      "closest_existing_id": "<pattern_id or null>",\n'
        '      "closest_existing_name": "<name or null>",\n'
        '      "relationship": "exact_match|looser_subset|stricter_superset|partial_overlap|novel",\n'
        '      "explanation": "<1–2 sentences: focus on which fields differ and the reconciliation precision impact>",\n'
        '      "recommendation": "skip|add|review"\n'
        "    }\n"
        "  ],\n"
        '  "summary": "<one sentence overall assessment>"\n'
        "}\n\n"
        "Relationship definitions:\n"
        "  exact_match       – fields are identical to an existing pattern\n"
        "  looser_subset     – identified uses fewer fields (more false-positive risk)\n"
        "  stricter_superset – identified uses more fields (higher precision, preferred)\n"
        "  partial_overlap   – shares some fields but also uses different ones\n"
        "  novel             – no meaningful field overlap with any existing pattern"
    )

    try:
        result = _llm_json_completion(prompt)
        result["group_name"] = group_name
        result["group_pattern_count"] = len(group_patterns)
        result["llm_available"] = True
        return result
    except Exception as exc:
        logger.warning("[compare_patterns] LLM unavailable (%s); falling back to field diff", exc)
        # Deterministic fallback: primary-key-aware Jaccard comparison
        # Qualifier fields (amount, direction, amount_variance) are guards, not identifiers —
        # sharing only qualifiers means the patterns are novel to each other, not similar.
        _PK_FIELDS = {"end_to_end_id", "pmt_ref", "invoice", "counterparty", "amount_sum"}
        comparisons = []
        for ip in identified:
            i_fields = set(_fields(ip))
            best: Optional[Dict] = None
            best_score = -1.0
            for gp in group_patterns:
                g_fields = set(_fields(gp))
                pk_i = i_fields & _PK_FIELDS
                pk_g = g_fields & _PK_FIELDS
                pk_union = len(pk_i | pk_g)
                score = len(pk_i & pk_g) / pk_union if pk_union else 0.0
                if score > best_score:
                    best_score = score
                    best = gp
            if best is None or best_score == 0:
                rel, rec, expl = "novel", "add", "No primary-key field overlap with any existing pattern."
            else:
                g_fields = set(_fields(best))
                missing = sorted(g_fields - i_fields)   # in group, not in identified
                extra   = sorted(i_fields - g_fields)   # in identified, not in group
                if not missing and not extra:
                    rel, rec = "exact_match", "skip"
                    expl = f"Identical fields to {best['pattern_name']}."
                elif not extra:
                    rel, rec = "looser_subset", "review"
                    expl = f"{best['pattern_name']} also requires [{', '.join(missing)}] — this pattern is less selective."
                elif not missing:
                    rel, rec = "stricter_superset", "add"
                    expl = f"Adds [{', '.join(extra)}] on top of {best['pattern_name']} — higher precision, fewer false positives."
                else:
                    rel, rec = "partial_overlap", "review"
                    expl = (
                        f"Shares [{', '.join(sorted(i_fields & g_fields))}] with "
                        f"{best['pattern_name']}, but differs on [{', '.join(missing)}] vs [{', '.join(extra)}]."
                    )
            comparisons.append({
                "identified_name": ip["pattern_name"],
                "closest_existing_id": best["pattern_id"] if best else None,
                "closest_existing_name": best["pattern_name"] if best else None,
                "relationship": rel,
                "explanation": expl,
                "recommendation": rec,
            })
        return {
            "comparisons": comparisons,
            "summary": "Field-level comparison (LLM unavailable).",
            "group_name": group_name,
            "group_pattern_count": len(group_patterns),
            "llm_available": False,
        }


def generate_mapping_regex(camt_path: Path, other_path: Path, max_examples: int = 10) -> Dict[str, object]:
    """Build LLM prompt samples using the large-file-safe ref index + streaming scanner."""
    value_to_entry, all_values = _build_camt_ref_index(camt_path)
    matched_records = _scan_flat_file_for_refs(other_path, value_to_entry, all_values)

    # Group matched flat-file lines by camt ntry_ref so each sample has
    # one CAMT entry and up to 3 representative flat-file lines.
    seen_ntry: Dict[str, Dict[str, object]] = {}
    for rec in matched_records:
        # A single flat-file line may match several CAMT values that all belong
        # to the same entry (e.g. TX-id + PMT-REF + INV all on one line).
        # Track which entry keys we have already appended this line for so the
        # line is added at most once per CAMT entry per flat-file line.
        keys_used_this_rec: set = set()
        for m in rec["matched"]:
            entry = m["camt_entry"]
            key = entry.get("ntry_ref") or entry.get("pmt_ref") or "?"
            if key not in seen_ntry:
                seen_ntry[key] = {
                    **entry,
                    "matched_text": [],
                }
            if key not in keys_used_this_rec and len(seen_ntry[key]["matched_text"]) < 3:
                seen_ntry[key]["matched_text"].append(rec["line"])
                keys_used_this_rec.add(key)
        if len(seen_ntry) >= max_examples:
            break

    samples = list(seen_ntry.values())[:max_examples]
    format_info = _infer_flat_file_format(matched_records)

    # Overall pattern-confidence score (0–100):
    #   65 % weight  — match ratio: unique CAMT entries found in the flat file
    #                   ÷ total CAMT entries with any indexable ref
    #   35 % weight  — structural clarity: how unambiguously the format was detected
    all_indexed_refs: Dict[str, Dict] = {}  # ntry_ref -> entry for all indexed entries
    for entry in value_to_entry.values():
        ref = entry.get("ntry_ref", "")
        if ref and ref not in all_indexed_refs:
            all_indexed_refs[ref] = entry

    matched_ntry_refs: set = set(
        m["camt_entry"].get("ntry_ref", "")
        for rec in matched_records
        for m in rec["matched"]
        if m["camt_entry"].get("ntry_ref")
    )

    unique_camt_total = len(all_indexed_refs)
    unique_camt_matched = len(matched_ntry_refs)

    unmatched_entries = [
        {
            "ntry_ref": ref,
            "amount": entry.get("amount"),
            "currency": entry.get("currency"),
            "counterparty": entry.get("counterparty"),
            "refs": entry.get("refs", {}),
            "pmt_ref": entry.get("pmt_ref"),
            "invoice": entry.get("invoice"),
        }
        for ref, entry in sorted(all_indexed_refs.items())
        if ref not in matched_ntry_refs
    ]
    if unmatched_entries:
        logger.warning(
            "generate_mapping_regex: %d CAMT entr%s not found in flat file: %s",
            len(unmatched_entries),
            "y" if len(unmatched_entries) == 1 else "ies",
            ", ".join(e["ntry_ref"] for e in unmatched_entries),
        )

    # Compute per-field hit rate against matched PSR lines and patch structural_field_info
    total_matched_lines = len(matched_records)
    structural_info = format_info.get("structural_field_info", {})
    for field, pattern in format_info.get("suggested_regex_map", {}).items():
        if field not in structural_info:
            continue
        try:
            compiled_field = re.compile(pattern)
            hits = sum(1 for rec in matched_records if compiled_field.search(rec["line"]))
        except Exception:
            hits = 0
        rate = hits / max(total_matched_lines, 1)
        pct = round(rate * 100, 1)
        level = "high" if rate >= 0.85 else "medium" if rate >= 0.60 else "low"
        structural_info[field]["confidence"] = level
        structural_info[field]["confidence_pct"] = pct
        structural_info[field]["hits"] = hits
        structural_info[field]["total"] = total_matched_lines

    match_ratio = unique_camt_matched / max(unique_camt_total, 1)
    structural_score = (
        1.00 if format_info["detected_type"] == "FIXED_WIDTH" else
        0.85 if format_info["detected_type"] == "DELIMITED" else
        0.30
    )
    pattern_confidence = round(
        min(structural_score * 0.35 + min(match_ratio, 1.0) * 0.65, 1.0) * 100, 1
    )

    try:
        _, psr_transactions = parse_psr_file(other_path)
        psr_transaction_count = len(psr_transactions)
    except Exception:
        psr_transaction_count = None

    prompt = _build_regex_prompt(samples)
    result: Dict[str, object] = {
        "examples": samples,
        "prompt": prompt,
        "llm_available": False,
        "format_info": format_info,
        "match_count": unique_camt_matched,
        "camt_ref_index_size": unique_camt_total,
        "psr_transaction_count": psr_transaction_count,
        "pattern_confidence": pattern_confidence,
        "llm_samples_sent": len(samples),
        "unmatched_camt_entries": unmatched_entries,
    }
    try:
        llm_output = _llm_json_completion(prompt)
        result["llm_available"] = True
        # Enrich any LLM-derived fields with the same data-driven hit-rate stats
        for field, info in (llm_output.get("field_extractors") or {}).items():
            pattern = info.get("regex", "")
            if not pattern:
                continue
            try:
                compiled_field = re.compile(pattern)
                hits = sum(1 for rec in matched_records if compiled_field.search(rec["line"]))
            except Exception:
                hits = 0
            rate = hits / max(total_matched_lines, 1)
            pct = round(rate * 100, 1)
            info["confidence"] = "high" if rate >= 0.85 else "medium" if rate >= 0.60 else "low"
            info["confidence_pct"] = pct
            info["hits"] = hits
            info["total"] = total_matched_lines
        result["llm_output"] = llm_output
    except ValueError as exc:
        result["llm_error"] = str(exc)
    except Exception as exc:
        result["llm_error"] = str(exc)
    return result


def _entries_missing_refs_or_unmatched(
    camt_path: Path, other_path: Path
) -> List[Dict[str, object]]:
    """Return CAMT entries that have no identifiers, or whose identifiers were
    not found anywhere in the flat file.

    Uses the same streaming ref-index + combined-regex scanner as
    ``recognize_files`` so it remains O(N + M) for large files.

    Each returned item has keys:
        entry      – the CAMT entry dict (refs shape: Dict[str, str])
        reason     – "no_refs" | "refs_present_but_not_found"
        refs_sample – list of the identifier values that were checked
    """
    value_to_entry, all_values = _build_camt_ref_index(camt_path)
    matched_records = _scan_flat_file_for_refs(other_path, value_to_entry, all_values)

    # which identifier values actually appeared in the flat file?
    found_values: set = {
        m["value"].upper()
        for rec in matched_records
        for m in rec["matched"]
    }

    problems: List[Dict[str, object]] = []

    # second iterparse pass: classify every Ntry
    context = ET.iterparse(str(camt_path), events=("end",))
    for _event, elem in context:
        if elem.tag.split("}")[-1] != "Ntry":
            continue

        ntry_ref = _first_text_by_local_name(elem, "NtryRef")
        txdtls = next(
            (e for e in elem.iter() if e.tag.split("}")[-1] == "TxDtls"), None
        )

        refs_map: Dict[str, str] = {}
        remittance = ""
        if txdtls is not None:
            refs_el = next(
                (e for e in txdtls.iter() if e.tag.split("}")[-1] == "Refs"), None
            )
            if refs_el is not None:
                for child in list(refs_el):
                    tag = child.tag.split("}")[-1]
                    val = (child.text or "").strip()
                    if val and val.upper() not in _SKIP_REF_VALUES:
                        refs_map[tag] = val
            rmtinf = next(
                (e for e in txdtls.iter() if e.tag.split("}")[-1] == "RmtInf"), None
            )
            if rmtinf is not None:
                remittance = _first_text_by_local_name(rmtinf, "Ustrd")

        pmt_ref_m = PMT_REF_RE.search(remittance)
        inv_m = INVOICE_RE.search(remittance)
        pmt_ref = pmt_ref_m.group(0).upper() if pmt_ref_m else ""
        invoice = inv_m.group(0).upper().replace(" ", "-") if inv_m else ""

        id_values: set = set()
        id_values.update(v.upper() for v in refs_map.values() if v)
        if pmt_ref:
            id_values.add(pmt_ref)
        if invoice:
            id_values.add(invoice)

        entry: Dict[str, object] = {
            "ntry_ref":    ntry_ref,
            "amount":      _first_text_by_local_name(elem, "Amt"),
            "currency":    next(
                (e.attrib.get("Ccy", "") for e in elem.iter()
                 if e.tag.split("}")[-1] == "Amt"), ""
            ),
            "direction":   _first_text_by_local_name(elem, "CdtDbtInd"),
            "booking_date": _first_text_by_local_name(elem, "Dt"),
            "remittance":  remittance,
            "refs":        refs_map,
            "pmt_ref":     pmt_ref,
            "invoice":     invoice,
        }

        if not id_values:
            problems.append({
                "entry": entry,
                "reason": "no_refs",
                "refs_sample": [],
            })
        elif not id_values.intersection(found_values):
            problems.append({
                "entry": entry,
                "reason": "refs_present_but_not_found",
                "refs_sample": list(id_values)[:5],
            })

        elem.clear()

    return problems


def suggest_patterns_for_unmatched(
    camt_path: Path, other_path: Path, max_examples: int = 8
) -> Dict[str, object]:
    """Use the LLM to propose extraction patterns for CAMT entries that either
    have no identifiers or whose identifiers could not be located in the flat file.

    Uses the streaming ref-index pipeline — the flat file is never fully loaded.
    """
    problems = _entries_missing_refs_or_unmatched(camt_path, other_path)
    samples = [p["entry"] for p in problems[:max_examples]]

    if not samples:
        raise ValueError(
            "No CAMT entries without refs or unmatched refs were found; "
            "LLM suggestions are not required."
        )

    prompt = _build_regex_prompt(samples)
    result: Dict[str, object] = {"examples": samples, "prompt": prompt, "llm_available": False}
    try:
        llm_output = _llm_json_completion(prompt)
        result["llm_available"] = True
        result["llm_output"] = llm_output
    except ValueError as exc:
        result["llm_error"] = str(exc)
    except Exception as exc:
        result["llm_error"] = str(exc)

    return result
