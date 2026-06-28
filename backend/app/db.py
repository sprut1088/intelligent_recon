from __future__ import annotations
import json, sqlite3
from typing import Any, Dict, Iterable, List, Optional
from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS psr_transactions (id TEXT PRIMARY KEY, execution_date TEXT, reference TEXT, amount REAL, direction TEXT, invoice TEXT, counterparty TEXT, currency TEXT, source_line INTEGER, raw_line TEXT);
CREATE TABLE IF NOT EXISTS camt_transactions (ntry_id TEXT PRIMARY KEY, camt_id TEXT, end_to_end_id TEXT, amount REAL, direction TEXT, booking_date TEXT, value_date TEXT, currency TEXT, remittance TEXT, counterparty TEXT, pmt_ref TEXT, invoice TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS recon_cases (case_id TEXT PRIMARY KEY, match_key TEXT, psr_id TEXT, camt_id TEXT, reference TEXT, invoice TEXT, counterparty TEXT, internal_amount REAL, bank_amount REAL, variance REAL, currency TEXT, value_date TEXT, booking_date TEXT, reconciliation_status TEXT, reason_code TEXT, match_type TEXT, match_confidence INTEGER, aging_days INTEGER, aging_bucket TEXT, rule_applied TEXT, exception_flag TEXT, explanation TEXT, feature_snapshot_json TEXT, suggestions_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS recon_user_action_event (event_id TEXT PRIMARY KEY, case_id TEXT, event_type TEXT, user_id TEXT, event_timestamp TEXT DEFAULT CURRENT_TIMESTAMP, event_payload_json TEXT);
CREATE TABLE IF NOT EXISTS recon_manual_resolution (resolution_id TEXT PRIMARY KEY, case_id TEXT, original_exception_type TEXT, final_resolution_type TEXT, reason_code TEXT, psr_transaction_ids_json TEXT, bank_transaction_ids_json TEXT, amount_variance REAL, date_variance_days INTEGER, fields_used_json TEXT, fields_ignored_json TEXT, user_comment TEXT, resolved_by TEXT, resolved_at TEXT DEFAULT CURRENT_TIMESTAMP, approved_by TEXT, reversed_flag INTEGER DEFAULT 0, learning_eligible INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS exception_workflow (case_id TEXT PRIMARY KEY, workflow_status TEXT DEFAULT 'NEW', owner TEXT DEFAULT 'Unassigned', priority TEXT DEFAULT 'Medium', sla_due_at TEXT, assigned_at TEXT, assigned_by TEXT, comments_json TEXT DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS recon_pattern_candidate (candidate_pattern_id TEXT PRIMARY KEY, pattern_name TEXT, discovered_from_reason_code TEXT, observed_case_count INTEGER, backtest_precision REAL, estimated_false_positive_rate REAL, proposed_rule_json TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS recon_pattern_registry (pattern_id TEXT PRIMARY KEY, pattern_name TEXT, pattern_type TEXT, pattern_group TEXT DEFAULT 'default', pattern_version TEXT DEFAULT '1.0', pattern_rule_json TEXT, status TEXT, execution_mode TEXT, confidence_threshold REAL, approved_by TEXT, approved_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS file_ingestion_batch (batch_id TEXT PRIMARY KEY, batch_name TEXT, status TEXT DEFAULT 'CREATED', created_by TEXT DEFAULT 'prototype_user', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, psr_file_id TEXT, camt_file_id TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS uploaded_file (file_id TEXT PRIMARY KEY, batch_id TEXT, file_type TEXT, original_filename TEXT, stored_path TEXT, file_size INTEGER, content_sha256 TEXT, status TEXT DEFAULT 'UPLOADED', profile_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS data_quality_issue (issue_id TEXT PRIMARY KEY, batch_id TEXT, file_id TEXT, severity TEXT, issue_code TEXT, field_name TEXT, record_id TEXT, message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS run_metadata (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_PATTERNS = [
    ("P1", "Exact EndToEndId Match", "SEED", {"fields": ["end_to_end_id"], "mode": "AUTO"}, "ACTIVE", "AUTO_CLOSE", 0.95),
    ("P2", "PMT-REF + Amount", "SEED", {"fields": ["pmt_ref", "amount"], "mode": "AUTO"}, "ACTIVE", "AUTO_CLOSE", 0.92),
    ("P3", "Invoice Extracted from Ustrd", "SEED", {"fields": ["invoice", "amount"], "mode": "AUTO"}, "ACTIVE", "AUTO_CLOSE", 0.90),
    ("P4", "Counterparty Fuzzy Match", "SEED", {"fields": ["counterparty", "amount"], "threshold": 0.85}, "ACTIVE", "SUGGESTION", 0.80),
    ("P5", "Exception Handling / Unmatch", "SEED", {"route_to": "manual_review"}, "ACTIVE", "MANUAL", 0.00),
    ("P6", "One-to-Many Bank Settlement", "SEED", {"fields": ["pmt_ref", "invoice", "amount_sum"]}, "ACTIVE", "SUGGESTION", 0.85),
    ("P7", "Amount Variance", "SEED", {"fields": ["identity", "amount_variance"], "minor_tolerance": settings.minor_variance_tolerance}, "ACTIVE", "LEDGER_OR_IN_TRANSIT", 0.75),
]

class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False

def get_conn() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.database_path), timeout=30.0, factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def seed_default_patterns(conn: sqlite3.Connection) -> None:
    for pattern_id, name, pattern_type, rule, status, mode, threshold in DEFAULT_PATTERNS:
        conn.execute("""INSERT OR IGNORE INTO recon_pattern_registry (pattern_id, pattern_name, pattern_type, pattern_group, pattern_version, pattern_rule_json, status, execution_mode, confidence_threshold, approved_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (pattern_id, name, pattern_type, "default", "1.0", json.dumps(rule), status, mode, threshold, "system_seed"))

def _ensure_pattern_group_column(conn: sqlite3.Connection) -> None:
    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(recon_pattern_registry)").fetchall()]
    if "pattern_group" not in existing_columns:
        conn.execute("ALTER TABLE recon_pattern_registry ADD COLUMN pattern_group TEXT DEFAULT 'default'")


def _ensure_pattern_version_column(conn: sqlite3.Connection) -> None:
    existing_columns = [row[1] for row in conn.execute("PRAGMA table_info(recon_pattern_registry)").fetchall()]
    if "pattern_version" not in existing_columns:
        conn.execute("ALTER TABLE recon_pattern_registry ADD COLUMN pattern_version TEXT DEFAULT '1.0'")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_pattern_group_column(conn)
        _ensure_pattern_version_column(conn)
        seed_default_patterns(conn)
        conn.commit()

def reset_runtime_tables(conn: sqlite3.Connection) -> None:
    for table in ["psr_transactions", "camt_transactions", "recon_cases", "exception_workflow", "recon_user_action_event", "recon_manual_resolution", "recon_pattern_candidate", "run_metadata"]:
        conn.execute(f"DELETE FROM {table}")
    seed_default_patterns(conn)

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    for key in list(item.keys()):
        if key.endswith("_json") and item[key]:
            try: item[key[:-5]] = json.loads(item[key])
            except json.JSONDecodeError: item[key[:-5]] = item[key]
    return item

def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [row_to_dict(row) for row in rows]

def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)

def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)", (key, str(value)))
