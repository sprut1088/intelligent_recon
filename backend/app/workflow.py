from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from .db import get_conn, json_dumps, row_to_dict, rows_to_dicts


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _sla_days_for_case(reason_code: str, confidence: int, variance: Optional[float]) -> int:
    if reason_code in {"AMOUNT_VARIANCE_MAJOR", "BANK_ONLY_UNMATCHED"}:
        return 1
    if variance is not None and abs(float(variance)) > 1000:
        return 1
    if confidence < 50:
        return 2
    return 3


def _priority_for_case(reason_code: str, confidence: int, variance: Optional[float]) -> str:
    if reason_code in {"AMOUNT_VARIANCE_MAJOR", "BANK_ONLY_UNMATCHED"}:
        return "High"
    if variance is not None and abs(float(variance)) > 1000:
        return "High"
    if confidence < 50:
        return "Medium"
    return "Low"


def sync_exception_workflow(conn=None) -> int:
    own_conn = conn is None
    conn = conn or get_conn()
    try:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO exception_workflow
            (case_id, workflow_status, owner, priority, sla_due_at, comments_json)
            SELECT
                case_id,
                'NEW',
                'Unassigned',
                CASE
                    WHEN reason_code IN ('AMOUNT_VARIANCE_MAJOR', 'BANK_ONLY_UNMATCHED') THEN 'High'
                    WHEN ABS(COALESCE(variance, 0)) > 1000 THEN 'High'
                    WHEN COALESCE(match_confidence, 0) < 50 THEN 'Medium'
                    ELSE 'Low'
                END,
                datetime(
                    'now',
                    CASE
                        WHEN reason_code IN ('AMOUNT_VARIANCE_MAJOR', 'BANK_ONLY_UNMATCHED') THEN '+1 days'
                        WHEN ABS(COALESCE(variance, 0)) > 1000 THEN '+1 days'
                        WHEN COALESCE(match_confidence, 0) < 50 THEN '+2 days'
                        ELSE '+3 days'
                    END
                ),
                '[]'
            FROM recon_cases
            WHERE exception_flag='Y'
            """
        )
        inserted = conn.total_changes - before
        if own_conn:
            conn.commit()
        return inserted
    finally:
        if own_conn:
            conn.close()


def list_exception_workflow(status: Optional[str] = None, owner: Optional[str] = None, priority: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict:
    with get_conn() as conn:
        sync_exception_workflow(conn)
        clauses = ["c.exception_flag='Y'"]
        params = []
        if status:
            clauses.append("w.workflow_status=?")
            params.append(status)
        if owner:
            clauses.append("w.owner=?")
            params.append(owner)
        if priority:
            clauses.append("w.priority=?")
            params.append(priority)
        where = "WHERE " + " AND ".join(clauses)
        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM recon_cases c JOIN exception_workflow w ON c.case_id=w.case_id {where}",
            params,
        ).fetchone()["cnt"]
        rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT c.*, w.workflow_status, w.owner, w.priority, w.sla_due_at, w.assigned_at, w.assigned_by, w.comments_json
                FROM recon_cases c
                JOIN exception_workflow w ON c.case_id=w.case_id
                {where}
                ORDER BY
                  CASE w.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                  w.sla_due_at ASC,
                  c.match_confidence ASC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        )
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


def get_exception_workflow(case_id: str) -> Dict:
    with get_conn() as conn:
        sync_exception_workflow(conn)
        row = conn.execute(
            """
            SELECT c.*, w.workflow_status, w.owner, w.priority, w.sla_due_at, w.assigned_at, w.assigned_by, w.comments_json
            FROM recon_cases c JOIN exception_workflow w ON c.case_id=w.case_id
            WHERE c.case_id=?
            """,
            (case_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Exception workflow not found for case {case_id}")
    return row_to_dict(row)


def update_exception_workflow(case_id: str, workflow_status: Optional[str] = None, owner: Optional[str] = None, priority: Optional[str] = None, comment: Optional[str] = None, updated_by: str = "prototype_user") -> Dict:
    with get_conn() as conn:
        sync_exception_workflow(conn)
        existing = conn.execute("SELECT * FROM exception_workflow WHERE case_id=?", (case_id,)).fetchone()
        if not existing:
            raise ValueError(f"Exception workflow not found for case {case_id}")

        fields = []
        params = []
        if workflow_status:
            fields.append("workflow_status=?")
            params.append(workflow_status)
        if owner:
            fields.append("owner=?")
            params.append(owner)
            fields.append("assigned_at=?")
            params.append(_utc_now().isoformat())
            fields.append("assigned_by=?")
            params.append(updated_by)
        if priority:
            fields.append("priority=?")
            params.append(priority)
        comments = json.loads(existing["comments_json"] or "[]")
        if comment:
            comments.append({"at": _utc_now().isoformat(), "by": updated_by, "comment": comment})
            fields.append("comments_json=?")
            params.append(json_dumps(comments))
        if not fields:
            return get_exception_workflow(case_id)
        fields.append("updated_at=CURRENT_TIMESTAMP")
        params.append(case_id)
        conn.execute(f"UPDATE exception_workflow SET {', '.join(fields)} WHERE case_id=?", params)
        conn.execute(
            "INSERT INTO recon_user_action_event (event_id, case_id, event_type, user_id, event_payload_json) VALUES (?, ?, ?, ?, ?)",
            (
                f"EVT-WF-{case_id}-{int(_utc_now().timestamp())}",
                case_id,
                "exception_workflow_updated",
                updated_by,
                json_dumps({"workflow_status": workflow_status, "owner": owner, "priority": priority, "comment": comment}),
            ),
        )
        conn.commit()
    return get_exception_workflow(case_id)


def mark_workflow_resolved(conn, case_id: str, updated_by: str = "prototype_user", comment: str = "Resolved through reconciliation workbench") -> None:
    row = conn.execute("SELECT comments_json FROM exception_workflow WHERE case_id=?", (case_id,)).fetchone()
    comments = json.loads(row["comments_json"] or "[]") if row else []
    comments.append({"at": _utc_now().isoformat(), "by": updated_by, "comment": comment})
    conn.execute(
        """
        INSERT INTO exception_workflow (case_id, workflow_status, owner, priority, comments_json)
        VALUES (?, 'RESOLVED', ?, 'Low', ?)
        ON CONFLICT(case_id) DO UPDATE SET workflow_status='RESOLVED', comments_json=excluded.comments_json, updated_at=CURRENT_TIMESTAMP
        """,
        (case_id, updated_by, json_dumps(comments)),
    )
