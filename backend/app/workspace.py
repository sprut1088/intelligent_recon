from __future__ import annotations

import csv
import io
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from fastapi.responses import StreamingResponse

from .db import get_conn, json_dumps, row_to_dict, rows_to_dicts, set_meta


CANONICAL_FIELDS = [
    {"field": "reference", "label": "Payment / bank reference", "type": "Text", "psr": "reference", "camt": "pmt_ref / end_to_end_id"},
    {"field": "invoice", "label": "Invoice / remittance tracking", "type": "Text", "psr": "invoice", "camt": "invoice / remittance"},
    {"field": "amount", "label": "Amount", "type": "Decimal", "psr": "amount", "camt": "amount"},
    {"field": "direction", "label": "Credit / debit direction", "type": "Text", "psr": "direction", "camt": "direction"},
    {"field": "counterparty", "label": "Counterparty name", "type": "Text", "psr": "counterparty", "camt": "counterparty"},
    {"field": "currency", "label": "Currency", "type": "Text", "psr": "currency", "camt": "currency"},
    {"field": "date", "label": "Execution / value / booking date", "type": "Date", "psr": "execution_date", "camt": "booking_date / value_date"},
]


def _count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()["cnt"])


def _profile_values(rows: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    values = [r.get(field) for r in rows]
    non_null = [v for v in values if v not in (None, "")]
    samples = []
    for v in non_null:
        if v not in samples:
            samples.append(v)
        if len(samples) == 3:
            break
    return {
        "field": field,
        "populated": len(non_null),
        "missing": len(values) - len(non_null),
        "distinct": len(set(str(v) for v in non_null)),
        "samples": samples,
    }


def _status_rows(conn) -> List[Dict[str, Any]]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT reconciliation_status AS label,
                   COUNT(*) AS value,
                   COALESCE(SUM(ABS(COALESCE(variance,0))),0) AS variance
            FROM recon_cases
            GROUP BY reconciliation_status
            ORDER BY value DESC
            """
        ).fetchall()
    )


def _summary_dict(conn) -> Dict[str, Any]:
    total = _count(conn, "recon_cases")
    exception_count = conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases WHERE exception_flag='Y'").fetchone()["cnt"]
    auto_closed = conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases WHERE reconciliation_status LIKE 'Matched%'").fetchone()["cnt"]
    avg_confidence = conn.execute("SELECT COALESCE(AVG(match_confidence),0) AS avgv FROM recon_cases").fetchone()["avgv"]
    variance = conn.execute("SELECT COALESCE(SUM(ABS(COALESCE(variance,0))),0) AS v FROM recon_cases").fetchone()["v"]
    return {
        "total_cases": total,
        "auto_closed": int(auto_closed or 0),
        "exceptions": int(exception_count or 0),
        "match_rate": round((auto_closed / total) * 100, 2) if total else 0,
        "average_confidence": round(float(avg_confidence or 0), 2),
        "absolute_variance": float(variance or 0),
        "psr_records": _count(conn, "psr_transactions"),
        "camt_entries": _count(conn, "camt_transactions"),
        "learning_events": _count(conn, "recon_user_action_event"),
        "learned_candidates": _count(conn, "recon_pattern_candidate"),
    }


def get_workspace_overview() -> Dict[str, Any]:
    with get_conn() as conn:
        summary = _summary_dict(conn)
        pattern_count = _count(conn, "recon_pattern_registry")
        active_patterns = conn.execute("SELECT COUNT(*) AS cnt FROM recon_pattern_registry WHERE status='ACTIVE'").fetchone()["cnt"]
        recent_cases = rows_to_dicts(conn.execute("SELECT * FROM recon_cases ORDER BY updated_at DESC LIMIT 5").fetchall())
        recent_events = rows_to_dicts(conn.execute("SELECT * FROM recon_user_action_event ORDER BY event_timestamp DESC LIMIT 5").fetchall())
    return {
        "process": {
            "process_id": "IRE-CASH-001",
            "name": "Cash Account Real-Time Reconciliation",
            "environment": "Prototype / UAT",
            "domain": "Treasury cash accounts",
            "currency": "EUR",
            "status": "Ready for client walkthrough",
            "owner": "Recon Ops Lead",
            "last_snapshot": "Snapshot generated from sample PSR/CAMT data",
        },
        "summary": summary,
        "capabilities": [
            {"name": "Data intake", "status": "Enabled", "detail": "PSR fixed-width and CAMT.053 XML uploads"},
            {"name": "Data prep", "status": "Enabled", "detail": "Canonical mapping, cleansing, validation and profiling"},
            {"name": "No-code rules", "status": "Enabled", "detail": f"{pattern_count} patterns, {active_patterns} active"},
            {"name": "AI assistance", "status": "Prototype", "detail": "Field prediction, explanation, learning inbox and assistant"},
            {"name": "Exception workflow", "status": "Enabled", "detail": "Owner, priority, SLA, comments and governance"},
            {"name": "Dashboards", "status": "Enabled", "detail": "Open breaks, ageing, root cause and rule performance"},
        ],
        "lifecycle": [
            {"step": "Extract", "detail": "Load PSR, CAMT and optional documents", "state": "complete"},
            {"step": "Transform", "detail": "Map to canonical fields and cleanse values", "state": "complete"},
            {"step": "Validate", "detail": "Check header, trailer, duplicates and nulls", "state": "complete"},
            {"step": "Reconcile", "detail": "Run multi-pass seed and learnt patterns", "state": "complete"},
            {"step": "Manage", "detail": "Route exceptions with SLA and ownership", "state": "active"},
            {"step": "Learn", "detail": "Promote repeated analyst resolutions", "state": "active"},
        ],
        "agent_insights": [
            "Field prediction recommends reference, invoice, amount, currency and counterparty as high-value match fields.",
            "In-transit items should be aged separately from amount breaks to avoid false manual workload.",
            "Learnt patterns should start in suggestion mode until back-tested and approved by a reconciliation lead.",
        ],
        "recent_cases": recent_cases,
        "recent_events": recent_events,
    }


def list_submissions() -> Dict[str, Any]:
    with get_conn() as conn:
        uploaded = rows_to_dicts(
            conn.execute(
                """
                SELECT f.*, b.batch_name, b.status AS batch_status
                FROM uploaded_file f
                LEFT JOIN file_ingestion_batch b ON f.batch_id=b.batch_id
                ORDER BY f.created_at DESC
                """
            ).fetchall()
        )
        if not uploaded:
            uploaded = [
                {
                    "file_id": "SAMPLE-PSR",
                    "batch_id": "SAMPLE-BATCH",
                    "batch_name": "Bundled sample data",
                    "file_type": "PSR",
                    "original_filename": "psr_10000 payments.txt",
                    "status": "PROCESSED",
                    "batch_status": "RECONCILED",
                    "file_size": None,
                    "content_sha256": "sample",
                    "profile": {"record_count": _count(conn, "psr_transactions"), "parser": "Fixed-width PSR"},
                    "created_at": "sample",
                },
                {
                    "file_id": "SAMPLE-CAMT",
                    "batch_id": "SAMPLE-BATCH",
                    "batch_name": "Bundled sample data",
                    "file_type": "CAMT",
                    "original_filename": "camt_10000 payments.xml",
                    "status": "PROCESSED",
                    "batch_status": "RECONCILED",
                    "file_size": None,
                    "content_sha256": "sample",
                    "profile": {"record_count": _count(conn, "camt_transactions"), "parser": "CAMT.053 XML"},
                    "created_at": "sample",
                },
            ]
        batches = rows_to_dicts(conn.execute("SELECT * FROM file_ingestion_batch ORDER BY created_at DESC LIMIT 20").fetchall())
    for item in uploaded:
        item["document_status"] = "Action required" if item.get("status") in ("UPLOADED", "VALIDATED_WITH_WARNINGS") else "Processed"
        item["used_in"] = item.get("batch_name") or item.get("batch_id")
        item["quality_badge"] = "Warning" if item.get("document_status") == "Action required" else "OK"
    return {"items": uploaded, "batches": batches}


def get_data_preview(limit: int = 10) -> Dict[str, Any]:
    with get_conn() as conn:
        psr = rows_to_dicts(conn.execute("SELECT * FROM psr_transactions ORDER BY id LIMIT ?", (limit,)).fetchall())
        camt = rows_to_dicts(conn.execute("SELECT * FROM camt_transactions ORDER BY ntry_id LIMIT ?", (limit,)).fetchall())
        psr_count = _count(conn, "psr_transactions")
        camt_count = _count(conn, "camt_transactions")
    psr_fields = ["id", "execution_date", "reference", "amount", "direction", "invoice", "counterparty", "currency"]
    camt_fields = ["ntry_id", "end_to_end_id", "pmt_ref", "amount", "direction", "booking_date", "value_date", "currency", "invoice", "counterparty"]
    return {
        "canonical_fields": CANONICAL_FIELDS,
        "psr": {"total": psr_count, "rows": psr, "profile": [_profile_values(psr, f) for f in psr_fields]},
        "camt": {"total": camt_count, "rows": camt, "profile": [_profile_values(camt, f) for f in camt_fields]},
        "normalisation_rules": [
            {"rule": "Trim whitespace and normalise case", "applies_to": "reference, invoice, counterparty"},
            {"rule": "Extract invoice token from CAMT remittance", "applies_to": "invoice"},
            {"rule": "Convert PSR/CAMT amount to decimal EUR", "applies_to": "amount"},
            {"rule": "Map CR/DR and CAMT CdtDbtInd into canonical direction", "applies_to": "direction"},
        ],
    }


def predict_match_fields() -> Dict[str, Any]:
    with get_conn() as conn:
        psr_count = _count(conn, "psr_transactions")
        camt_count = _count(conn, "camt_transactions")
    predictions = [
        {"left_field": "reference", "right_field": "pmt_ref", "confidence": 98, "type": "Reference", "rationale": "PSR PMT-REF and CAMT payment reference share the same business identifier."},
        {"left_field": "reference", "right_field": "end_to_end_id", "confidence": 93, "type": "Reference", "rationale": "EndToEndId is a strong ISO 20022 correlation key where populated."},
        {"left_field": "invoice", "right_field": "invoice", "confidence": 96, "type": "Enrichment", "rationale": "Invoice can be parsed from CAMT remittance and compared to PSR tracking reference."},
        {"left_field": "amount", "right_field": "amount", "confidence": 99, "type": "Amount", "rationale": "Decimal amount is a high-strength control field after scaling validation."},
        {"left_field": "currency", "right_field": "currency", "confidence": 99, "type": "Control", "rationale": "Currency must match before auto-close or ledger allocation."},
        {"left_field": "counterparty", "right_field": "counterparty", "confidence": 89, "type": "Fuzzy", "rationale": "Names may have aliases; use similarity as supporting evidence rather than sole evidence."},
        {"left_field": "execution_date", "right_field": "booking_date", "confidence": 82, "type": "Timing", "rationale": "Date tolerance supports in-transit classification and predictive clearing."},
    ]
    return {
        "status": "predicted",
        "analysed_records": {"psr": psr_count, "camt": camt_count},
        "predictions": predictions,
        "recommended_match_set": ["reference", "invoice", "amount", "currency", "counterparty", "date_tolerance"],
    }


def get_no_code_rules() -> Dict[str, Any]:
    with get_conn() as conn:
        patterns = rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry ORDER BY pattern_id").fetchall())
    rule_text = []
    for pattern in patterns:
        mode = pattern.get("execution_mode") or "SUGGESTION"
        if pattern["pattern_id"] == "P1":
            nrl = "If EndToEndId matches exactly and currency matches, reconcile automatically."
        elif pattern["pattern_id"] == "P2":
            nrl = "If PMT-REF and amount match, reconcile automatically."
        elif pattern["pattern_id"] == "P3":
            nrl = "If invoice extracted from remittance equals PSR invoice and amount matches, reconcile."
        elif pattern["pattern_id"] == "P4":
            nrl = "If amount and currency match and counterparty similarity is above threshold, propose a match."
        elif pattern["pattern_id"] == "P6":
            nrl = "If one bank entry equals a group of payment rows and identity tokens align, propose a grouped match."
        elif pattern["pattern_id"] == "P7":
            nrl = "If identity fields match but amount differs within tolerance, route to ledger or in-transit review."
        else:
            nrl = "Route unresolved or low-confidence cases to manual exception handling."
        rule_text.append({**pattern, "natural_rule": nrl, "mode": mode})
    return {"items": rule_text}


def get_workflow_rules() -> Dict[str, Any]:
    rules = [
        {
            "rule_id": "WF-001",
            "name": "Auto-close high confidence cash matches",
            "condition": "If confidence >= 95 and variance = 0",
            "actions": ["Set status to Matched & Settled", "Remove from exception proofing", "Record audit event"],
            "enabled": True,
        },
        {
            "rule_id": "WF-002",
            "name": "Label amount breaks",
            "condition": "If identity fields match and amount variance is not zero",
            "actions": ["Label as Amount Break", "Route to Ledger Review", "Calculate short/over candidate"],
            "enabled": True,
        },
        {
            "rule_id": "WF-003",
            "name": "Route in-transit payments",
            "condition": "If PSR exists and no CAMT entry exists",
            "actions": ["Label as Uncleared / In-Transit", "Age until next CAMT", "Escalate after threshold"],
            "enabled": True,
        },
        {
            "rule_id": "WF-004",
            "name": "Escalate aged breaks",
            "condition": "If ageing bucket is 4-7 days or 7+ days",
            "actions": ["Set priority to High", "Assign to Recon Lead", "Require comment"],
            "enabled": True,
        },
        {
            "rule_id": "WF-005",
            "name": "Learning signal capture",
            "condition": "If analyst manually resolves no-candidate exception",
            "actions": ["Capture reason code", "Capture trusted fields", "Mine repeated behaviour"],
            "enabled": True,
        },
    ]
    return {"items": rules}


def get_dashboard_model() -> Dict[str, Any]:
    with get_conn() as conn:
        summary = _summary_dict(conn)
        by_status = _status_rows(conn)
        by_rule = rows_to_dicts(conn.execute("SELECT COALESCE(rule_applied,'Unclassified') AS label, COUNT(*) AS value FROM recon_cases GROUP BY rule_applied ORDER BY value DESC LIMIT 8").fetchall())
        by_reason = rows_to_dicts(conn.execute("SELECT COALESCE(reason_code,'Unclassified') AS label, COUNT(*) AS value FROM recon_cases GROUP BY reason_code ORDER BY value DESC LIMIT 8").fetchall())
        by_age = rows_to_dicts(conn.execute("SELECT COALESCE(aging_bucket,'0-1 day') AS label, COUNT(*) AS value FROM recon_cases WHERE exception_flag='Y' GROUP BY aging_bucket ORDER BY value DESC").fetchall())
        by_owner = rows_to_dicts(conn.execute("SELECT COALESCE(owner,'Unassigned') AS label, COUNT(*) AS value FROM exception_workflow GROUP BY owner ORDER BY value DESC").fetchall())
        by_priority = rows_to_dicts(conn.execute("SELECT COALESCE(priority,'Medium') AS label, COUNT(*) AS value FROM exception_workflow GROUP BY priority ORDER BY value DESC").fetchall())
    return {
        "summary": summary,
        "charts": {
            "by_status": by_status,
            "by_rule": by_rule,
            "by_reason": by_reason,
            "by_age": by_age,
            "by_owner": by_owner,
            "by_priority": by_priority,
        },
        "root_cause_insights": [
            "Amount variance cases should be split between ledger candidates and expected clearing items.",
            "No acceptable candidate cases are the best source for learning new patterns.",
            "Exact PMT-REF and invoice extraction provide the safest auto-close paths for cash reconciliation.",
        ],
    }


def create_snapshot() -> Dict[str, Any]:
    with get_conn() as conn:
        snapshot_id = f"SNAP-{uuid.uuid4().hex[:8].upper()}"
        set_meta(conn, "last_snapshot_id", snapshot_id)
        conn.execute(
            "INSERT INTO recon_user_action_event (event_id, case_id, event_type, user_id, event_payload_json) VALUES (?, ?, ?, ?, ?)",
            (f"EVT-{uuid.uuid4().hex[:10].upper()}", "PROCESS", "snapshot_created", "prototype_user", json_dumps({"snapshot_id": snapshot_id})),
        )
        conn.commit()
    return {"snapshot_id": snapshot_id, "status": "CREATED"}


def export_reconciliation_results() -> StreamingResponse:
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM recon_cases ORDER BY case_id").fetchall())
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "case_id", "psr_id", "camt_id", "reference", "invoice", "counterparty", "internal_amount",
            "bank_amount", "variance", "currency", "reconciliation_status", "reason_code", "match_confidence",
            "rule_applied", "exception_flag", "explanation",
        ],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=intelligent_recon_results.csv"},
    )
