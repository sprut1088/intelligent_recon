from __future__ import annotations

import logging
import uuid
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import settings
from .db import get_conn, json_dumps, rows_to_dicts
from .ingestion import get_batch
from .parsers import parse_camt_file, parse_psr_file

logger = logging.getLogger(__name__)


def _issue_id() -> str:
    return f"DQ-{uuid.uuid4().hex[:10].upper()}"


def _issue(batch_id: str, file_id: str, severity: str, code: str, field: str, record_id: str, message: str) -> Dict:
    return {
        "issue_id": _issue_id(),
        "batch_id": batch_id,
        "file_id": file_id,
        "severity": severity,
        "issue_code": code,
        "field_name": field,
        "record_id": record_id,
        "message": message,
    }


def _raw_lines(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle]


def _profile_psr(batch_id: str, file_info: Dict) -> tuple[Dict, List[Dict]]:
    path = Path(file_info["stored_path"])
    file_id = file_info["file_id"]
    issues: List[Dict] = []
    lines = _raw_lines(path)
    header_lines = [line for line in lines if line.startswith("10")]
    trailer_lines = [line for line in lines if line.startswith("99")]
    detail_lines = [line for line in lines if line.startswith("20")]

    if not header_lines:
        issues.append(_issue(batch_id, file_id, "ERROR", "PSR_HEADER_MISSING", "record_type", "FILE", "PSR file does not contain a Record Type 10 header."))
    if not trailer_lines:
        issues.append(_issue(batch_id, file_id, "WARNING", "PSR_TRAILER_MISSING", "record_type", "FILE", "PSR trailer Record Type 99 is missing. Continue for prototype, but confirm production file-control requirement."))

    header, transactions = parse_psr_file(path)
    ids = [txn.id for txn in transactions]
    for txn_id, count in Counter(ids).items():
        if count > 1:
            issues.append(_issue(batch_id, file_id, "ERROR", "DUPLICATE_PSR_ID", "id", txn_id, f"PSR transaction ID appears {count} times."))

    for txn in transactions:
        if not txn.reference:
            issues.append(_issue(batch_id, file_id, "WARNING", "PSR_REFERENCE_MISSING", "reference", txn.id, "Expected bank reference / PMT-REF is blank."))
        if not txn.invoice:
            issues.append(_issue(batch_id, file_id, "WARNING", "PSR_INVOICE_MISSING", "invoice", txn.id, "Invoice or tracking reference is blank."))
        if not txn.counterparty:
            issues.append(_issue(batch_id, file_id, "WARNING", "PSR_COUNTERPARTY_MISSING", "counterparty", txn.id, "Counterparty name is blank."))
        if txn.amount <= 0:
            issues.append(_issue(batch_id, file_id, "ERROR", "PSR_AMOUNT_INVALID", "amount", txn.id, "Amount must be greater than zero."))
        if txn.direction not in {"CR", "DR"}:
            issues.append(_issue(batch_id, file_id, "ERROR", "PSR_DIRECTION_INVALID", "direction", txn.id, "Direction must be CR or DR."))

    total_amount = round(sum(txn.amount for txn in transactions), 2)
    average_amount = round(total_amount / len(transactions), 2) if transactions else 0
    if transactions and average_amount < 10:
        issues.append(_issue(batch_id, file_id, "WARNING", "PSR_AMOUNT_SCALE_SUSPECT", "amount", "FILE", "Average PSR amount is very low. Check PSR_AMOUNT_DIVISOR and client decimal rules."))

    profile = {
        "file_type": "PSR",
        "header_present": bool(header_lines),
        "trailer_present": bool(trailer_lines),
        "raw_line_count": len(lines),
        "transaction_count": len(transactions),
        "detail_record_count": len(detail_lines),
        "currency": header.currency if header else "EUR",
        "total_amount": total_amount,
        "average_amount": average_amount,
        "warning_count": sum(1 for i in issues if i["severity"] == "WARNING"),
        "error_count": sum(1 for i in issues if i["severity"] == "ERROR"),
    }
    return profile, issues


def _profile_camt(batch_id: str, file_info: Dict) -> tuple[Dict, List[Dict]]:
    path = Path(file_info["stored_path"])
    file_id = file_info["file_id"]
    issues: List[Dict] = []
    transactions = parse_camt_file(path)

    ids = [txn.ntry_id for txn in transactions]
    for txn_id, count in Counter(ids).items():
        if count > 1:
            issues.append(_issue(batch_id, file_id, "ERROR", "DUPLICATE_CAMT_ENTRY", "ntry_id", txn_id, f"CAMT entry ID appears {count} times."))

    for txn in transactions:
        if txn.amount <= 0:
            issues.append(_issue(batch_id, file_id, "ERROR", "CAMT_AMOUNT_INVALID", "amount", txn.ntry_id, "CAMT amount must be greater than zero."))
        if txn.direction not in {"CR", "DR"}:
            issues.append(_issue(batch_id, file_id, "ERROR", "CAMT_DIRECTION_INVALID", "direction", txn.ntry_id, "CAMT credit/debit indicator must resolve to CR or DR."))
        if not txn.pmt_ref:
            issues.append(_issue(batch_id, file_id, "WARNING", "CAMT_PMT_REF_MISSING", "pmt_ref", txn.ntry_id, "PMT-REF could not be extracted from remittance text."))
        if not txn.invoice:
            issues.append(_issue(batch_id, file_id, "WARNING", "CAMT_INVOICE_MISSING", "invoice", txn.ntry_id, "Invoice could not be extracted from remittance text."))
        if not txn.counterparty:
            issues.append(_issue(batch_id, file_id, "WARNING", "CAMT_COUNTERPARTY_MISSING", "counterparty", txn.ntry_id, "Counterparty name is blank or not available in CAMT."))

    currencies = sorted({txn.currency for txn in transactions if txn.currency})
    total_amount = round(sum(txn.amount for txn in transactions), 2)
    profile = {
        "file_type": "CAMT",
        "entry_count": len(transactions),
        "currency": currencies[0] if len(currencies) == 1 else ",".join(currencies),
        "currency_count": len(currencies),
        "total_amount": total_amount,
        "warning_count": sum(1 for i in issues if i["severity"] == "WARNING"),
        "error_count": sum(1 for i in issues if i["severity"] == "ERROR"),
    }
    return profile, issues


def validate_batch(batch_id: str) -> Dict:
    logger.info("Validating batch %s", batch_id)
    batch = get_batch(batch_id)
    files = batch.get("files", [])
    if not files:
        raise ValueError("No uploaded files exist for this batch")

    all_issues: List[Dict] = []
    profiles: Dict[str, Dict] = {}

    for file_info in files:
        if file_info["file_type"] == "PSR":
            profile, issues = _profile_psr(batch_id, file_info)
        elif file_info["file_type"] == "CAMT":
            profile, issues = _profile_camt(batch_id, file_info)
        else:
            profile, issues = {"file_type": file_info["file_type"]}, []
        profiles[file_info["file_id"]] = profile
        all_issues.extend(issues)

    psr_profiles = [p for p in profiles.values() if p.get("file_type") == "PSR"]
    camt_profiles = [p for p in profiles.values() if p.get("file_type") == "CAMT"]
    if not psr_profiles:
        all_issues.append(_issue(batch_id, "", "ERROR", "BATCH_PSR_MISSING", "file_type", "BATCH", "Batch does not contain a PSR file."))
    if not camt_profiles:
        all_issues.append(_issue(batch_id, "", "ERROR", "BATCH_CAMT_MISSING", "file_type", "BATCH", "Batch does not contain a CAMT file."))
    if psr_profiles and camt_profiles and psr_profiles[0].get("currency") != camt_profiles[0].get("currency"):
        all_issues.append(_issue(batch_id, "", "ERROR", "BATCH_CURRENCY_MISMATCH", "currency", "BATCH", "PSR and CAMT currencies do not match."))

    errors = sum(1 for issue in all_issues if issue["severity"] == "ERROR")
    warnings = sum(1 for issue in all_issues if issue["severity"] == "WARNING")
    status = "QUALITY_ERRORS" if errors else "VALIDATED"

    with get_conn() as conn:
        conn.execute("DELETE FROM data_quality_issue WHERE batch_id=?", (batch_id,))
        conn.executemany(
            """
            INSERT INTO data_quality_issue
            (issue_id, batch_id, file_id, severity, issue_code, field_name, record_id, message)
            VALUES (:issue_id, :batch_id, :file_id, :severity, :issue_code, :field_name, :record_id, :message)
            """,
            all_issues,
        )
        for file_id, profile in profiles.items():
            conn.execute("UPDATE uploaded_file SET profile_json=?, status='PROFILED' WHERE file_id=?", (json_dumps(profile), file_id))
        conn.execute("UPDATE file_ingestion_batch SET status=?, updated_at=CURRENT_TIMESTAMP WHERE batch_id=?", (status, batch_id))
        conn.commit()

    logger.info("validate_batch %s done: errors=%d warnings=%d", batch_id, errors, warnings)
    return get_quality_report(batch_id)


def get_quality_report(batch_id: str) -> Dict:
    batch = get_batch(batch_id)
    with get_conn() as conn:
        issues = rows_to_dicts(conn.execute("SELECT * FROM data_quality_issue WHERE batch_id=? ORDER BY severity, issue_code, record_id", (batch_id,)).fetchall())
    return {
        "batch_id": batch_id,
        "batch_status": batch.get("status"),
        "files": batch.get("files", []),
        "error_count": sum(1 for issue in issues if issue["severity"] == "ERROR"),
        "warning_count": sum(1 for issue in issues if issue["severity"] == "WARNING"),
        "issues": issues,
    }
