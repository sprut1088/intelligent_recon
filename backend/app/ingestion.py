from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional

from fastapi import UploadFile

logger = logging.getLogger(__name__)

from .config import settings
from .db import get_conn, json_dumps, row_to_dict, rows_to_dicts, set_meta
from .loader import CASE_INSERT_SQL
from .parsers import CamtTransaction, PsrTransaction, parse_camt_file, parse_psr_file
from .reconciliation import case_to_db_tuple, reconcile_transactions
from .workflow import sync_exception_workflow

UPLOAD_ROOT = settings.runtime_data_dir / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "_", name or "upload.dat").strip()
    return cleaned or "upload.dat"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_upload_to_temp(upload: UploadFile, temp_dir: Path) -> Path:
    upload.file.seek(0)
    filename = _safe_filename(upload.filename or "upload.dat")
    target_path = temp_dir / filename
    with target_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target_path


def create_batch(batch_name: Optional[str] = None, created_by: str = "prototype_user") -> Dict:
    batch_id = _new_id("BATCH")
    batch_name = batch_name or f"Recon upload {batch_id}"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO file_ingestion_batch (batch_id, batch_name, status, created_by)
            VALUES (?, ?, 'CREATED', ?)
            """,
            (batch_id, batch_name, created_by),
        )
        conn.commit()
    return get_batch(batch_id)


def store_uploaded_file(
    upload: UploadFile,
    file_type: str,
    batch_id: Optional[str] = None,
    batch_name: Optional[str] = None,
    created_by: str = "prototype_user",
) -> Dict:
    file_type = (file_type or "").upper().strip()
    if file_type not in {"PSR", "CAMT"}:
        raise ValueError("file_type must be PSR or CAMT")
    logger.info("Storing uploaded file: type=%s batch_id=%s filename=%s", file_type, batch_id, upload.filename)

    if not batch_id:
        batch_id = create_batch(batch_name=batch_name, created_by=created_by)["batch_id"]

    file_id = _new_id(file_type)
    batch_dir = UPLOAD_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(upload.filename or f"{file_type.lower()}_upload.dat")
    stored_path = batch_dir / f"{file_id}_{filename}"

    with stored_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)

    profile = {
        "filename": filename,
        "file_type": file_type,
        "message": "Uploaded. Deep validation runs in the Data Quality step.",
    }
    file_size = stored_path.stat().st_size
    digest = _sha256(stored_path)

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO uploaded_file
            (file_id, batch_id, file_type, original_filename, stored_path, file_size, content_sha256, status, profile_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'UPLOADED', ?)
            """,
            (file_id, batch_id, file_type, filename, str(stored_path), file_size, digest, json_dumps(profile)),
        )
        if file_type == "PSR":
            conn.execute(
                "UPDATE file_ingestion_batch SET psr_file_id=?, status='UPLOADED', updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                (file_id, batch_id),
            )
        else:
            conn.execute(
                "UPDATE file_ingestion_batch SET camt_file_id=?, status='UPLOADED', updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                (file_id, batch_id),
            )
        conn.commit()

    return {"batch": get_batch(batch_id), "file": get_file(file_id)}


def get_file(file_id: str) -> Dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM uploaded_file WHERE file_id=?", (file_id,)).fetchone()
        if not row:
            raise ValueError(f"File not found: {file_id}")
    return row_to_dict(row)


def list_batches(limit: int = 50, offset: int = 0) -> Dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM file_ingestion_batch").fetchone()["cnt"]
        rows = rows_to_dicts(
            conn.execute(
                "SELECT * FROM file_ingestion_batch ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        )
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


def get_batch(batch_id: str) -> Dict:
    with get_conn() as conn:
        batch = conn.execute("SELECT * FROM file_ingestion_batch WHERE batch_id=?", (batch_id,)).fetchone()
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")
        files = rows_to_dicts(
            conn.execute("SELECT * FROM uploaded_file WHERE batch_id=? ORDER BY created_at", (batch_id,)).fetchall()
        )
    return {**row_to_dict(batch), "files": files}


def _batch_file_paths(batch_id: str) -> tuple[Path, Path]:
    batch = get_batch(batch_id)
    psr = next((f for f in batch["files"] if f["file_type"] == "PSR"), None)
    camt = next((f for f in batch["files"] if f["file_type"] == "CAMT"), None)
    if not psr or not camt:
        raise ValueError("Batch must contain one PSR file and one CAMT file before reconciliation can run")
    return Path(psr["stored_path"]), Path(camt["stored_path"])


_CANDIDATE_DIVISORS = (1.0, 100.0)


def _sniff_psr_divisor(psr_path: Path, camt_transactions: list) -> float:
    """Auto-detect the PSR amount divisor.

    Parses PSR with divisor=1 to obtain raw integers, then scores each
    candidate divisor (1 and 100) by checking how many of the first 50
    PSR transactions have an amount that matches a CAMT transaction amount
    (looked up by reference or invoice key).  The divisor with the highest
    score wins; ties favour the global default.
    """
    if not camt_transactions:
        logger.info("PSR divisor sniff skipped: no CAMT transactions, using default %s", settings.psr_amount_divisor)
        return settings.psr_amount_divisor

    # Parse PSR with raw (divisor=1) to get unscaled integers.
    _, raw_txns = parse_psr_file(psr_path, amount_divisor=1.0)
    if not raw_txns:
        return settings.psr_amount_divisor

    # Build reference/invoice → CAMT amount lookup.
    camt_by_key: Dict[str, float] = {}
    for txn in camt_transactions:
        for key in (txn.pmt_ref, txn.end_to_end_id, txn.invoice):
            k = (key or "").strip().upper()
            if k:
                camt_by_key[k] = txn.amount

    if not camt_by_key:
        logger.info("PSR divisor sniff skipped: no CAMT reference keys, using default %s", settings.psr_amount_divisor)
        return settings.psr_amount_divisor

    scores: Dict[float, int] = {d: 0 for d in _CANDIDATE_DIVISORS}
    for txn in raw_txns[:50]:
        camt_amt: Optional[float] = None
        for key in (txn.reference, txn.invoice):
            k = (key or "").strip().upper()
            if k in camt_by_key:
                camt_amt = camt_by_key[k]
                break
        if camt_amt is None:
            continue
        for divisor in _CANDIDATE_DIVISORS:
            scaled = txn.amount / divisor
            tolerance = max(0.01, abs(camt_amt) * 0.001)
            if abs(scaled - camt_amt) <= tolerance:
                scores[divisor] += 1

    best = max(_CANDIDATE_DIVISORS, key=lambda d: (scores[d], d == settings.psr_amount_divisor))
    logger.info("PSR divisor sniff: scores=%s → auto-selected %s", scores, best)
    return best


def run_uploaded_batch(batch_id: str, amount_divisor: Optional[float] = None, reset_transactions: bool = True, pattern_group: Optional[str] = None) -> Dict:
    psr_path, camt_path = _batch_file_paths(batch_id)
    camt_transactions = parse_camt_file(camt_path)

    if amount_divisor is None:
        amount_divisor = _sniff_psr_divisor(psr_path, camt_transactions)

    header, psr_transactions = parse_psr_file(psr_path, amount_divisor=amount_divisor)

    with get_conn() as conn:
        if reset_transactions:
            conn.execute("DELETE FROM psr_transactions")
            conn.execute("DELETE FROM camt_transactions")
            conn.execute("DELETE FROM recon_cases")

        conn.executemany(
            """
            INSERT OR REPLACE INTO psr_transactions
            (id, execution_date, reference, amount, direction, invoice, counterparty, currency, source_line, raw_line)
            VALUES (:id, :execution_date, :reference, :amount, :direction, :invoice, :counterparty, :currency, :source_line, :raw_line)
            """,
            [asdict(txn) for txn in psr_transactions],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO camt_transactions
            (ntry_id, camt_id, end_to_end_id, amount, direction, booking_date, value_date, currency, remittance, counterparty, pmt_ref, invoice, raw_json)
            VALUES (:ntry_id, :camt_id, :end_to_end_id, :amount, :direction, :booking_date, :value_date, :currency, :remittance, :counterparty, :pmt_ref, :invoice, :raw_json)
            """,
            [{**asdict(txn), "raw_json": json_dumps(txn.raw)} for txn in camt_transactions],
        )
        if pattern_group:
            patterns = rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry WHERE pattern_group = ? ORDER BY pattern_id", (pattern_group,)).fetchall())
        else:
            patterns = rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry ORDER BY pattern_id").fetchall())
        cases = reconcile_transactions(psr_transactions, camt_transactions, patterns)
        conn.execute("DELETE FROM recon_cases")
        conn.executemany(CASE_INSERT_SQL, [case_to_db_tuple(case) for case in cases])
        sync_exception_workflow(conn)
        set_meta(conn, "active_batch_id", batch_id)
        set_meta(conn, "last_load_header", json.dumps(asdict(header) if header else {}))
        set_meta(conn, "last_amount_divisor", amount_divisor or settings.psr_amount_divisor)
        set_meta(conn, "psr_count", len(psr_transactions))
        set_meta(conn, "camt_count", len(camt_transactions))
        set_meta(conn, "case_count", len(cases))
        conn.execute("UPDATE file_ingestion_batch SET status='RECONCILED', updated_at=CURRENT_TIMESTAMP WHERE batch_id=?", (batch_id,))
        conn.commit()

    return {
        "batch_id": batch_id,
        "psr_count": len(psr_transactions),
        "camt_count": len(camt_transactions),
        "case_count": len(cases),
        "amount_divisor": amount_divisor or settings.psr_amount_divisor,
    }
