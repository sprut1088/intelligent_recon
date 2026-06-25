from __future__ import annotations

import logging
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import UploadFile

from .config import settings
from .parsers import CamtTransaction, PsrTransaction, parse_camt_file, parse_psr_file

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
                camt_refs_map = _extract_camt_refs_map(camt_path)
                text_lines = [line.rstrip("\n") for line in other_path.open("r", encoding="utf-8", errors="replace")]
                header, psr_transactions = parse_psr_file(other_path)
                other_details["camt_refs_count"] = sum(len(v) for v in camt_refs_map.values())
                other_details["psr_transaction_count"] = len(psr_transactions)
                other_details["parsed_as"] = "PSR" if psr_transactions else "TEXT"
                matches = []
                value_to_tags: Dict[str, List[str]] = {}
                for tag, vals in camt_refs_map.items():
                    for v in vals:
                        value_to_tags.setdefault(v, []).append(tag)

                for i, line in enumerate(text_lines, start=1):
                    found: List[Dict[str, str]] = []
                    for val, tags in value_to_tags.items():
                        if val and val in line:
                            for t in tags:
                                found.append({"tag": t, "value": val})
                    if found:
                        matches.append({"line_no": i, "line": line.strip(), "matched": found})

                other_details["line_count"] = len(text_lines)
                other_details["matches"] = matches
                other_details["match_count"] = len(matches)
                other_details["refs_map_sample"] = {k: list(v)[:5] for k, v in list(camt_refs_map.items())[:10]} if camt_refs_map else {}
                other_details["parse_success"] = bool(psr_transactions)
            except Exception:
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


def generate_reconciliation_patterns(
    camt_path: Path,
    other_path: Path,
    provided_regex_map: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    camt_transactions = _load_camt(camt_path)
    _, psr_transactions = parse_psr_file(other_path)
    if not psr_transactions:
        raise ValueError("Uploaded file could not be parsed as a PSR transaction file.")
    return _build_reconciliation_pattern(camt_transactions, psr_transactions, provided_regex_map)


def _build_regex_prompt(samples: List[Dict[str, object]]) -> str:
    example_text = []
    for i, sample in enumerate(samples, start=1):
        example_text.append(f"ENTRY {i}:")
        for key in ("ntry_ref", "amount", "currency", "direction", "booking_date", "counterparty", "remittance"):
            example_text.append(f"- {key}: {sample.get(key, '')}")
        refs = sample.get("refs", {})
        if refs:
            example_text.append("- refs:")
            for tag, values in refs.items():
                example_text.append(f"  - {tag}: {values}")
        matched = sample.get("matched_text", [])
        if matched:
            example_text.append("- matched_text:")
            for line in matched:
                example_text.append(f"  - {line}")
        example_text.append("")

    prompt = (
        "You are a regex expert for CAMT.053 reconciliation.\n"
        "Given CAMT.053 XML entry values and example rows from a matching settlement file (PSR or text extract), propose extraction patterns that help reconcile the bank statement entry against the internal record.\n"
        "The CAMT.053 entry may include EndToEndId, InstrId, NtryRef, Refs child tags, booking date, amount, counterparty, and remittance/unstructured reference text.\n"
        "Construct a mapping that can identify the following fields from the text file rows:\n"
        "- end_to_end_id (or other CAMT reference IDs if available)\n"
        "- amount\n"
        "- booking_date\n"
        "- counterparty name\n"
        "- remittance / unstructured reference string\n"
        "Focus on patterns that help match CAMT.053 entries to PSR/transaction records in a reconciliation workflow.\n"
        "Return only valid JSON with keys: regex_map and explanation.\n"
        "regex_map should be an object with fields for end_to_end_id, amount, booking_date, counterparty, remittance.\n"
        "If a pattern is ambiguous, return a sensible fallback.\n"
        "Do not include markdown.\n"
        "Examples:\n"
        + "\n".join(example_text)
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


def _build_mapping_samples(camt_entries: List[Dict[str, object]], text_lines: List[str], limit: int = 10) -> List[Dict[str, object]]:
    samples: List[Dict[str, object]] = []
    for entry in camt_entries:
        if len(samples) >= limit:
            break
        search_values = []
        for vals in entry.get("refs", {}).values():
            search_values.extend(vals)
        if entry.get("ntry_ref"):
            search_values.append(entry["ntry_ref"])
        if entry.get("amount"):
            search_values.append(entry["amount"])
        if entry.get("booking_date"):
            search_values.append(entry["booking_date"])

        matched_lines = []
        for line in text_lines:
            if any(val and val in line for val in search_values):
                matched_lines.append(line)
            if len(matched_lines) >= 3:
                break

        samples.append({
            "ntry_ref": entry.get("ntry_ref", ""),
            "amount": entry.get("amount", ""),
            "currency": entry.get("currency", ""),
            "direction": entry.get("direction", ""),
            "booking_date": entry.get("booking_date", ""),
            "counterparty": entry.get("counterparty", ""),
            "remittance": entry.get("remittance", ""),
            "refs": entry.get("refs", {}),
            "matched_text": matched_lines,
        })
    return samples


def generate_mapping_regex(camt_path: Path, other_path: Path, max_examples: int = 10) -> Dict[str, object]:
    camt_entries = _load_camt_entries(camt_path)
    text_lines = [line.rstrip("\n") for line in other_path.open("r", encoding="utf-8", errors="replace")]
    samples = _build_mapping_samples(camt_entries, text_lines, limit=max_examples)
    prompt = _build_regex_prompt(samples)
    result: Dict[str, object] = {
        "examples": samples,
        "prompt": prompt,
        "llm_available": False,
    }
    try:
        llm_output = _llm_json_completion(prompt)
        result["llm_available"] = True
        result["llm_output"] = llm_output
    except ValueError as exc:
        result["llm_error"] = str(exc)
    except Exception as exc:
        result["llm_error"] = str(exc)
    return result


def _entries_missing_refs_or_unmatched(camt_path: Path, other_path: Path) -> List[Dict[str, object]]:
    """Return CAMT entries that either have no refs or have refs that are not found in the other file's text lines.

    Each item is a dict with keys: entry, reason ("no_refs"|"refs_present_but_not_found"), refs_sample, matched_text_sample
    """
    camt_entries = _load_camt_entries(camt_path)
    text_lines = [line.rstrip("\n") for line in other_path.open("r", encoding="utf-8", errors="replace")]
    problems: List[Dict[str, object]] = []
    for entry in camt_entries:
        refs = entry.get("refs", {}) or {}
        # collect all reference values
        ref_values = []
        for vals in refs.values():
            ref_values.extend([v for v in vals if v])
        if entry.get("ntry_ref"):
            ref_values.append(entry.get("ntry_ref"))

        if not ref_values:
            problems.append({"entry": entry, "reason": "no_refs", "refs_sample": {}, "matched_text_sample": []})
            continue

        # check whether any ref value occurs in the other file lines
        found = []
        for v in ref_values:
            for line in text_lines:
                if v and v in line:
                    found.append({"value": v, "line": line.strip()})
                    break

        if not found:
            problems.append({"entry": entry, "reason": "refs_present_but_not_found", "refs_sample": ref_values[:5], "matched_text_sample": []})

    return problems


def suggest_patterns_for_unmatched(camt_path: Path, other_path: Path, max_examples: int = 8) -> Dict[str, object]:
    """Use the LLM to propose extraction patterns for CAMT entries that lack usable refs or matches.

    Returns a structure with example samples and the LLM JSON output when available.
    """
    camt_entries = _load_camt_entries(camt_path)
    text_lines = [line.rstrip("\n") for line in other_path.open("r", encoding="utf-8", errors="replace")]

    # Build samples focusing on problematic entries
    problems = _entries_missing_refs_or_unmatched(camt_path, other_path)
    samples = []
    for p in problems[:max_examples]:
        samples.append(p["entry"])

    if not samples:
        raise ValueError("No CAMT entries without refs or unmatched refs were found; LLM suggestions are not required.")

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
