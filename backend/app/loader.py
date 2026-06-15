from __future__ import annotations
import json
import logging
from dataclasses import asdict
from typing import Dict, List, Optional
from .config import settings
from .db import get_conn, json_dumps, reset_runtime_tables, rows_to_dicts, set_meta
from .parsers import CamtTransaction, PsrTransaction, parse_camt_file, parse_psr_file
from .reconciliation import case_to_db_tuple, reconcile_transactions
from .workflow import sync_exception_workflow

logger = logging.getLogger(__name__)

CASE_INSERT_SQL = """
INSERT INTO recon_cases
(case_id, match_key, psr_id, camt_id, reference, invoice, counterparty, internal_amount, bank_amount,
 variance, currency, value_date, booking_date, reconciliation_status, reason_code, match_type,
 match_confidence, aging_days, aging_bucket, rule_applied, exception_flag, explanation,
 feature_snapshot_json, suggestions_json)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

def load_samples_and_reconcile(amount_divisor: Optional[float] = None, reset: bool = True) -> Dict:
    logger.info("Loading sample data (reset=%s, divisor=%s)", reset, amount_divisor or settings.psr_amount_divisor)
    header, psr_transactions = parse_psr_file(settings.psr_sample_path, amount_divisor=amount_divisor)
    camt_transactions = parse_camt_file(settings.camt_sample_path)
    logger.info("Parsed %d PSR and %d CAMT transactions", len(psr_transactions), len(camt_transactions))
    with get_conn() as conn:
        if reset: reset_runtime_tables(conn)
        conn.executemany("""INSERT OR REPLACE INTO psr_transactions (id, execution_date, reference, amount, direction, invoice, counterparty, currency, source_line, raw_line) VALUES (:id, :execution_date, :reference, :amount, :direction, :invoice, :counterparty, :currency, :source_line, :raw_line)""", [asdict(txn) for txn in psr_transactions])
        conn.executemany("""INSERT OR REPLACE INTO camt_transactions (ntry_id, camt_id, end_to_end_id, amount, direction, booking_date, value_date, currency, remittance, counterparty, pmt_ref, invoice, raw_json) VALUES (:ntry_id, :camt_id, :end_to_end_id, :amount, :direction, :booking_date, :value_date, :currency, :remittance, :counterparty, :pmt_ref, :invoice, :raw_json)""", [{**asdict(txn), "raw_json": json_dumps(txn.raw)} for txn in camt_transactions])
        patterns = rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry").fetchall())
        cases = reconcile_transactions(psr_transactions, camt_transactions, patterns)
        conn.execute("DELETE FROM recon_cases")
        conn.executemany(CASE_INSERT_SQL, [case_to_db_tuple(case) for case in cases])
        sync_exception_workflow(conn)
        set_meta(conn, "last_load_header", json.dumps(asdict(header) if header else {}))
        set_meta(conn, "last_amount_divisor", amount_divisor or settings.psr_amount_divisor)
        set_meta(conn, "psr_count", len(psr_transactions)); set_meta(conn, "camt_count", len(camt_transactions)); set_meta(conn, "case_count", len(cases))
        conn.commit()
    logger.info("load_samples_and_reconcile complete: psr=%d camt=%d cases=%d", len(psr_transactions), len(camt_transactions), len(cases))
    return {"psr_count": len(psr_transactions), "camt_count": len(camt_transactions), "case_count": len(cases), "amount_divisor": amount_divisor or settings.psr_amount_divisor}

def rerun_reconciliation_only() -> Dict:
    logger.info("Re-running reconciliation from existing DB transactions")
    with get_conn() as conn:
        psr_rows = conn.execute("SELECT * FROM psr_transactions").fetchall(); camt_rows = conn.execute("SELECT * FROM camt_transactions").fetchall(); patterns = rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry").fetchall())
        psr_transactions: List[PsrTransaction] = [PsrTransaction(row["id"], row["execution_date"], row["reference"], row["amount"], row["direction"], row["invoice"], row["counterparty"], row["currency"], row["source_line"], row["raw_line"]) for row in psr_rows]
        camt_transactions: List[CamtTransaction] = [CamtTransaction(row["ntry_id"], row["camt_id"], row["end_to_end_id"], row["amount"], row["direction"], row["booking_date"], row["value_date"], row["currency"], row["remittance"], row["counterparty"], row["pmt_ref"], row["invoice"], json.loads(row["raw_json"] or "{}")) for row in camt_rows]
        cases = reconcile_transactions(psr_transactions, camt_transactions, patterns)
        conn.execute("DELETE FROM recon_cases"); conn.executemany(CASE_INSERT_SQL, [case_to_db_tuple(case) for case in cases]); set_meta(conn, "case_count", len(cases)); conn.commit()
    logger.info("rerun_reconciliation_only complete: cases=%d", len(cases))
    return {"case_count": len(cases)}
