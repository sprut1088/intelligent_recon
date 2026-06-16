from __future__ import annotations
import logging
import time
import uuid
from typing import Optional
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .db import get_conn, init_db, json_dumps, row_to_dict, rows_to_dicts
from .learning import approve_candidate, run_learning, seed_demo_learning_signals
from .ingestion import get_batch, list_batches, run_uploaded_batch, store_uploaded_file
from .loader import load_samples_and_reconcile, rerun_reconciliation_only
from .quality import get_quality_report, validate_batch
from .workflow import get_exception_workflow, list_exception_workflow, mark_workflow_resolved, update_exception_workflow
from .workspace import create_snapshot, export_reconciliation_results, get_dashboard_model, get_data_preview, get_no_code_rules, get_workspace_overview, get_workflow_rules, list_submissions, predict_match_fields
from .schemas import CandidateApprovalRequest, CaseResolveRequest, PatternCreateRequest, PatternUpdateRequest, ReconcileRunRequest, UserEventRequest, WorkflowUpdateRequest
from .ai_triage import build_ai_snapshot, run_tier2b, run_tier2c

# Module-level logger — format applied in startup() after uvicorn finishes its own logging setup
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _access_and_exception_log(request: Request, call_next):
    """Log every request with method, path, status, and duration.
    Any unhandled exception is logged with a full traceback before re-raising."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s — %s (%.0fms)", request.method, request.url.path, response.status_code, duration_ms)
        return response
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.exception("Unhandled exception in %s %s (%.0fms)", request.method, request.url.path, duration_ms)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

@app.on_event("startup")
def startup() -> None:
    # Re-apply our logging format here — uvicorn's dictConfig runs before this
    # event fires, so force=True will win and persist for the life of the process.
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    init_db()
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases").fetchone()["cnt"]
    if existing == 0:
        logger.info("No existing cases — loading sample data...")
        load_samples_and_reconcile(reset=True)
        with get_conn() as conn:
            existing = conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases").fetchone()["cnt"]
    logger.info("Startup complete. DB ready. recon_cases=%d", existing)

@app.get("/health")
def health() -> dict:
    return {"status":"ok","app":settings.app_name,"version":settings.app_version}


@app.post("/api/files/upload")
def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(...),
    batch_id: Optional[str] = Form(None),
    batch_name: Optional[str] = Form(None),
    created_by: str = Form("prototype_user"),
) -> dict:
    try:
        return store_uploaded_file(file, file_type=file_type, batch_id=batch_id, batch_name=batch_name, created_by=created_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/files/batches")
def files_batches(limit:int=Query(50,ge=1,le=200), offset:int=Query(0,ge=0)) -> dict:
    return list_batches(limit=limit, offset=offset)

@app.get("/api/files/batches/{batch_id}")
def files_batch_detail(batch_id: str) -> dict:
    try:
        return get_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/files/batches/{batch_id}/run")
def run_uploaded_file_batch(batch_id: str, request: ReconcileRunRequest = ReconcileRunRequest()) -> dict:
    try:
        return run_uploaded_batch(batch_id, amount_divisor=request.amount_divisor, reset_transactions=request.reset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/data-quality/batches/{batch_id}/validate")
def validate_uploaded_batch(batch_id: str) -> dict:
    try:
        return validate_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/data-quality/batches/{batch_id}")
def data_quality_report(batch_id: str) -> dict:
    try:
        return get_quality_report(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/load-sample")
def load_sample(request: ReconcileRunRequest = ReconcileRunRequest()) -> dict:
    return load_samples_and_reconcile(amount_divisor=request.amount_divisor, reset=request.reset)

@app.post("/api/reconcile/run")
def run_reconcile() -> dict:
    return rerun_reconciliation_only()



_ZONE_CFG = {
    "clear": {
        "prefix": "AI",
        "status": "AI-Assisted Suggested Match",
        "reason_code": "AI_EMBEDDING_MATCH",
        "suggestion_action": "CONFIRM_AI_MATCH",
        "tier_label": "2b",
    },
    "maybe": {
        "prefix": "AI-MAYBE",
        "status": "AI - Analyst Adjudication Required",
        "reason_code": "AI_MAYBE_ZONE",
        "suggestion_action": "ROUTE_TO_ANALYST",
        "tier_label": "2b_maybe",
    },
}

_AI_CASE_INSERT_SQL = """
INSERT OR REPLACE INTO recon_cases
   (case_id, psr_id, camt_id, reconciliation_status, reason_code,
    match_type, match_confidence, rule_applied, exception_flag,
    explanation, suggestions_json, feature_snapshot_json,
    reference, invoice, counterparty, internal_amount, bank_amount,
    variance, currency, value_date, booking_date,
    created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
"""


@app.post("/api/reconcile/ai-triage")
def run_ai_triage() -> dict:
    """
    Pass 2 AI residual triage.
    Tier 2b: embedding similarity on unmatched PSR pool.
    Stores AI cases in recon_cases then hands 'maybe' zone records to Tier 2c.
    """
    logger.info("AI triage requested")
    candidates = run_tier2b()
    clear = [c for c in candidates if c["zone"] == "clear"]
    maybe = [c for c in candidates if c["zone"] == "maybe"]
    logger.info("Tier 2b complete: %d total candidates (%d clear, %d maybe)", len(candidates), len(clear), len(maybe))

    inserted = 0
    with get_conn() as conn:
        # Remove previous AI suggestions so reruns are idempotent.
        # Use case_id prefix (always "AI-…") not reconciliation_status, which
        # Tier 2c may have overwritten to "Uncleared / In-Transit Payment" for
        # NO_MATCH decisions — those ghost rows must be cleaned up too.
        conn.execute("DELETE FROM recon_cases WHERE case_id LIKE 'AI%'")

        for c in candidates:
            zone = c["zone"]
            cfg = _ZONE_CFG[zone]
            case_id = f"{cfg['prefix']}-{c['psr_id']}-{c['camt_id']}"
            conf = int(c["cosine_score"] * 100)
            internal_amt = c.get("psr_amount")
            bank_amt = c.get("camt_amount")
            variance = (
                round(float(internal_amt) - float(bank_amt), 2)
                if internal_amt is not None and bank_amt is not None
                else None
            )
            explanation = (
                f"Embedding cosine similarity {c['cosine_score']:.4f}. "
                f"PSR text: '{c['psr_text']}'. CAMT text: '{c['camt_text']}'."
                if zone == "clear" else
                f"Embedding similarity {c['cosine_score']:.4f} \u2014 in 'maybe' zone (0.60\u20130.84). "
                f"Awaiting LLM adjudication (Tier 2c)."
            )
            conn.execute(_AI_CASE_INSERT_SQL, (
                case_id, c["psr_id"], c["camt_id"],
                cfg["status"], cfg["reason_code"], "1_TO_1",
                conf, "TIER2B_EMBEDDING", "Y",
                explanation,
                json_dumps([{
                    "action": cfg["suggestion_action"],
                    "confidence": c["cosine_score"],
                    "tier": cfg["tier_label"],
                    "camt_id": c["camt_id"],
                }]),
                json_dumps(build_ai_snapshot(c, conf, "TIER2B_EMBEDDING")),
                c.get("psr_reference") or c.get("camt_pmt_ref"),
                c.get("psr_invoice") or c.get("camt_invoice"),
                c.get("psr_counterparty") or c.get("camt_counterparty"),
                internal_amt, bank_amt, variance,
                c.get("psr_currency") or c.get("camt_currency") or "EUR",
                c.get("psr_execution_date") or "",
                c.get("camt_booking_date") or "",
            ))
            inserted += 1

        conn.commit()

    llm_decisions = run_tier2c(maybe)
    logger.info(
        "AI triage complete: inserted=%d clear=%d maybe=%d llm_adjudicated=%d",
        inserted, len(clear), len(maybe), len(llm_decisions),
    )

    return {
        "status": "ok",
        "inserted_count": inserted,
        "clear_count": len(clear),
        "maybe_count": len(maybe),
        "llm_adjudicated_count": len(llm_decisions),
        "skipped_count": len(candidates) - len(clear) - len(maybe),
    }

@app.get("/api/reconcile/summary")
def summary() -> dict:
    with get_conn() as conn:
        total=conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases").fetchone()["cnt"]
        psr_count=conn.execute("SELECT COUNT(*) AS cnt FROM psr_transactions").fetchone()["cnt"]
        camt_count=conn.execute("SELECT COUNT(*) AS cnt FROM camt_transactions").fetchone()["cnt"]
        status_rows=rows_to_dicts(conn.execute("SELECT reconciliation_status, COUNT(*) AS count, COALESCE(SUM(ABS(COALESCE(variance,0))),0) AS variance_abs FROM recon_cases GROUP BY reconciliation_status ORDER BY count DESC").fetchall())
        reason_rows=rows_to_dicts(conn.execute("SELECT reason_code, COUNT(*) AS count FROM recon_cases GROUP BY reason_code ORDER BY count DESC LIMIT 10").fetchall())
        pattern_rows=rows_to_dicts(conn.execute("SELECT rule_applied, COUNT(*) AS count FROM recon_cases GROUP BY rule_applied ORDER BY count DESC").fetchall())
        manual_resolution_count=conn.execute("SELECT COUNT(*) AS cnt FROM recon_manual_resolution").fetchone()["cnt"]
        learning_candidate_count=conn.execute("SELECT COUNT(*) AS cnt FROM recon_pattern_candidate").fetchone()["cnt"]
        kpi=row_to_dict(conn.execute("SELECT COALESCE(SUM(COALESCE(internal_amount,0)),0) AS internal_amount, COALESCE(SUM(COALESCE(bank_amount,0)),0) AS bank_amount, COALESCE(SUM(ABS(COALESCE(variance,0))),0) AS absolute_variance, COALESCE(AVG(match_confidence),0) AS average_confidence, SUM(CASE WHEN exception_flag='Y' THEN 1 ELSE 0 END) AS exception_count, SUM(CASE WHEN reconciliation_status LIKE 'Matched%' THEN 1 ELSE 0 END) AS auto_matched_count FROM recon_cases").fetchone())
    return {"total_cases":total,"psr_count":psr_count,"camt_count":camt_count,"manual_resolution_count":manual_resolution_count,"learning_candidate_count":learning_candidate_count,"kpi":kpi,"by_status":status_rows,"by_reason":reason_rows,"by_rule":pattern_rows}


@app.get("/api/workspace/overview")
def workspace_overview() -> dict:
    return get_workspace_overview()

@app.get("/api/workspace/submissions")
def workspace_submissions() -> dict:
    return list_submissions()

@app.get("/api/workspace/data-preview")
def workspace_data_preview(limit:int=Query(10,ge=1,le=50)) -> dict:
    return get_data_preview(limit=limit)

@app.get("/api/workspace/match-field-predictions")
def workspace_match_field_predictions() -> dict:
    return predict_match_fields()

@app.get("/api/workspace/no-code-rules")
def workspace_no_code_rules() -> dict:
    return get_no_code_rules()

@app.get("/api/workspace/workflow-rules")
def workspace_workflow_rules() -> dict:
    return get_workflow_rules()

@app.get("/api/workspace/dashboard")
def workspace_dashboard() -> dict:
    return get_dashboard_model()

@app.post("/api/workspace/snapshot")
def workspace_snapshot() -> dict:
    return create_snapshot()

@app.get("/api/workspace/export/reconciliation-results")
def workspace_export_results():
    return export_reconciliation_results()

@app.get("/api/reconcile/cases")
def list_cases(status: Optional[str]=None, exception_only: bool=False, search: Optional[str]=None, limit:int=Query(100,ge=1,le=1000), offset:int=Query(0,ge=0)) -> dict:
    clauses=[]; params=[]
    if status: clauses.append("reconciliation_status = ?"); params.append(status)
    if exception_only: clauses.append("exception_flag = 'Y'")
    if search:
        clauses.append("(case_id LIKE ? OR psr_id LIKE ? OR camt_id LIKE ? OR reference LIKE ? OR invoice LIKE ? OR counterparty LIKE ?)")
        term=f"%{search}%"; params.extend([term]*6)
    where="WHERE "+" AND ".join(clauses) if clauses else ""
    with get_conn() as conn:
        total=conn.execute(f"SELECT COUNT(*) AS cnt FROM recon_cases {where}", params).fetchone()["cnt"]
        rows=rows_to_dicts(conn.execute(f"SELECT * FROM recon_cases {where} ORDER BY exception_flag DESC, match_confidence ASC, case_id ASC LIMIT ? OFFSET ?", [*params,limit,offset]).fetchall())
    return {"total":total,"limit":limit,"offset":offset,"items":rows}

@app.get("/api/reconcile/cases/{case_id}")
def get_case(case_id: str) -> dict:
    with get_conn() as conn:
        row=conn.execute("SELECT * FROM recon_cases WHERE case_id=?", (case_id,)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Case not found")
        events=rows_to_dicts(conn.execute("SELECT * FROM recon_user_action_event WHERE case_id=? ORDER BY event_timestamp DESC", (case_id,)).fetchall())
        resolutions=rows_to_dicts(conn.execute("SELECT * FROM recon_manual_resolution WHERE case_id=? ORDER BY resolved_at DESC", (case_id,)).fetchall())
        case_dict = row_to_dict(row)
        # Augment with raw transaction fields not stored on recon_cases
        psr_id = case_dict.get("psr_id")
        camt_id = case_dict.get("camt_id")
        if psr_id:
            psr_row = conn.execute("SELECT direction FROM psr_transactions WHERE id = ?", (psr_id,)).fetchone()
            if psr_row:
                case_dict["psr_direction"] = psr_row["direction"]
        # match_key = bank.ntry_id (PK) for every case that has a bank side.
        # Always look up by ntry_id first; camt_id may be a non-unique sentinel
        # (e.g. "NOTFOUND") from bank feeds that omit the EndToEndId field.
        if camt_id:
            match_key = case_dict.get("match_key", "")
            camt_row = conn.execute("SELECT direction, remittance, pmt_ref, invoice, counterparty FROM camt_transactions WHERE ntry_id = ?", (match_key,)).fetchone()
            if not camt_row:
                camt_row = conn.execute("SELECT direction, remittance, pmt_ref, invoice, counterparty FROM camt_transactions WHERE camt_id = ?", (camt_id,)).fetchone()
            if camt_row:
                case_dict["camt_direction"] = camt_row["direction"]
                case_dict["camt_remittance"] = camt_row["remittance"]
                case_dict["camt_pmt_ref"] = camt_row["pmt_ref"]
                case_dict["camt_invoice"] = camt_row["invoice"]
                case_dict["camt_counterparty"] = camt_row["counterparty"]
    return {"case": case_dict, "events": events, "manual_resolutions": resolutions}


@app.get("/api/reconcile/cases/{case_id}/explanation")
def get_case_explanation(case_id: str) -> dict:
    details = get_case(case_id)
    case = details["case"]
    feature_snapshot = case.get("feature_snapshot") or {}
    return {
        "case_id": case_id,
        "rule_applied": case.get("rule_applied"),
        "reconciliation_status": case.get("reconciliation_status"),
        "explanation": case.get("explanation"),
        "feature_snapshot": feature_snapshot,
        "score_breakdown": feature_snapshot.get("score_breakdown", {}),
        "suggestions": case.get("suggestions") or [],
    }

@app.get("/api/reconcile/cases/{case_id}/similar")
def get_similar_cases(case_id: str, limit: int = Query(5, ge=1, le=20)) -> dict:
    RESOLVED_STATUSES = (
        "Matched & Settled (Auto-Close)",
        "Resolved Manually",
        "AI-Assisted Suggested Match",
        "Post to Short or Over Ledger",
    )
    with get_conn() as conn:
        current = conn.execute(
            "SELECT rule_applied FROM recon_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if not current or not current["rule_applied"]:
            return {"items": [], "count": 0}
        placeholders = ",".join("?" * len(RESOLVED_STATUSES))
        rows = rows_to_dicts(conn.execute(
            f"""SELECT case_id, psr_id, rule_applied, reconciliation_status, updated_at
                FROM recon_cases
                WHERE case_id != ?
                  AND rule_applied = ?
                  AND reconciliation_status IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT ?""",
            (case_id, current["rule_applied"], *RESOLVED_STATUSES, limit)
        ).fetchall())
    return {"items": rows, "count": len(rows)}

@app.post("/api/reconcile/cases/{case_id}/resolve")
def resolve_case(case_id: str, request: CaseResolveRequest) -> dict:
    with get_conn() as conn:
        case=conn.execute("SELECT * FROM recon_cases WHERE case_id=?", (case_id,)).fetchone()
        if not case: raise HTTPException(status_code=404, detail="Case not found")
        event_id=f"EVT-{uuid.uuid4().hex[:10].upper()}"; resolution_id=f"RES-{uuid.uuid4().hex[:10].upper()}"
        selected_psr=request.selected_psr_ids or ([case["psr_id"]] if case["psr_id"] else [])
        selected_bank=request.selected_bank_ids or ([case["camt_id"]] if case["camt_id"] else [])
        # Override path: mark as not eligible for learning signal
        is_override = bool(request.override_reason)
        effective_learning_eligible = False if is_override else request.learning_eligible
        effective_comment = request.comment
        if is_override:
            note_part = f" Note: {request.override_note}" if request.override_note else ""
            effective_comment = f"Override reason: {request.override_reason}.{note_part}"
        payload={"case_id":case_id,"resolution_type":request.resolution_type,"reason_code":request.reason_code,"selected_psr_ids":selected_psr,"selected_bank_ids":selected_bank,"fields_used":request.fields_used,"fields_ignored":request.fields_ignored,"accepted_variance":request.accepted_variance,"comment":effective_comment,"previous_engine_confidence":case["match_confidence"],"final_user_confidence":request.final_user_confidence,"override_reason":request.override_reason,"override_note":request.override_note}
        conn.execute("INSERT INTO recon_user_action_event (event_id, case_id, event_type, user_id, event_payload_json) VALUES (?, ?, 'exception_resolved', 'prototype_user', ?)", (event_id,case_id,json_dumps(payload)))
        conn.execute("INSERT INTO recon_manual_resolution (resolution_id, case_id, original_exception_type, final_resolution_type, reason_code, psr_transaction_ids_json, bank_transaction_ids_json, amount_variance, date_variance_days, fields_used_json, fields_ignored_json, user_comment, resolved_by, learning_eligible) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prototype_user', ?)", (resolution_id,case_id,case["reconciliation_status"],request.resolution_type,request.reason_code,json_dumps(selected_psr),json_dumps(selected_bank),request.accepted_variance if request.accepted_variance is not None else case["variance"],case["aging_days"],json_dumps(request.fields_used),json_dumps(request.fields_ignored),effective_comment,1 if effective_learning_eligible else 0))
        conn.execute("UPDATE recon_cases SET reconciliation_status='Resolved Manually', reason_code=?, exception_flag='N', explanation=?, updated_at=CURRENT_TIMESTAMP WHERE case_id=?", (request.reason_code,f"Resolved by analyst as {request.resolution_type}. Learning signal {'excluded (override)' if is_override else 'captured'}.",case_id))
        mark_workflow_resolved(conn, case_id, updated_by="prototype_user", comment=f"Resolved as {request.resolution_type}")
        conn.commit()
    return {"case_id":case_id,"event_id":event_id,"resolution_id":resolution_id,"status":"resolved"}

@app.post("/api/reconcile/events")
def capture_event(request: UserEventRequest) -> dict:
    event_id=f"EVT-{uuid.uuid4().hex[:10].upper()}"
    with get_conn() as conn:
        conn.execute("INSERT INTO recon_user_action_event (event_id, case_id, event_type, user_id, event_payload_json) VALUES (?, ?, ?, ?, ?)", (event_id,request.case_id,request.event_type,request.user_id,json_dumps(request.payload)))
        conn.commit()
    return {"event_id":event_id,"status":"captured"}


@app.get("/api/events")
def list_events(limit:int=Query(50,ge=1,le=500), offset:int=Query(0,ge=0)) -> dict:
    with get_conn() as conn:
        total=conn.execute("SELECT COUNT(*) AS cnt FROM recon_user_action_event").fetchone()["cnt"]
        rows=rows_to_dicts(conn.execute("SELECT * FROM recon_user_action_event ORDER BY event_timestamp DESC LIMIT ? OFFSET ?", (limit,offset)).fetchall())
    return {"total":total,"limit":limit,"offset":offset,"items":rows}


@app.get("/api/exceptions/workflow")
def exception_workflow_queue(
    status: Optional[str]=None,
    owner: Optional[str]=None,
    priority: Optional[str]=None,
    limit:int=Query(100,ge=1,le=1000),
    offset:int=Query(0,ge=0),
) -> dict:
    return list_exception_workflow(status=status, owner=owner, priority=priority, limit=limit, offset=offset)

@app.get("/api/exceptions/{case_id}/workflow")
def exception_workflow_detail(case_id: str) -> dict:
    try:
        return get_exception_workflow(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.patch("/api/exceptions/{case_id}/workflow")
def update_exception_workflow_route(case_id: str, request: WorkflowUpdateRequest) -> dict:
    try:
        return update_exception_workflow(
            case_id,
            workflow_status=request.workflow_status,
            owner=request.owner,
            priority=request.priority,
            comment=request.comment,
            updated_by=request.updated_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/assistant/query")
def assistant_query(question: str) -> dict:
    q=(question or "").lower()
    s=summary()
    total=s["total_cases"]; auto=s["kpi"].get("auto_matched_count") or 0; ex=s["kpi"].get("exception_count") or 0
    match_rate=round((auto/total)*100,2) if total else 0
    variance=s["kpi"].get("absolute_variance") or 0
    learnt=s.get("learning_candidate_count",0)
    if "exception" in q:
        answer=f"There are {ex} exception cases currently routed for ledger allocation, in-transit monitoring, or manual review."
    elif "auto" in q or "match rate" in q:
        answer=f"{auto} cases are auto-closed, giving an auto-close match rate of {match_rate}%."
    elif "variance" in q:
        answer=f"The current absolute variance across reconciliation cases is EUR {variance:,.2f}."
    elif "learning" in q or "pattern" in q:
        answer=f"There are {learnt} learned-pattern candidates in the governance inbox. Approved learned patterns run in suggestion mode first."
    else:
        answer=f"Current run contains {total} cases, {auto} auto-closed matches, {ex} exceptions, and an average confidence of {s['kpi'].get('average_confidence',0):.2f}%."
    return {"question": question, "answer": answer, "summary": s}

@app.get("/api/patterns")
def list_patterns() -> dict:
    with get_conn() as conn: rows=rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry ORDER BY pattern_id").fetchall())
    return {"items":rows}


@app.post("/api/patterns")
def create_pattern(request: PatternCreateRequest) -> dict:
    pattern_id = request.pattern_id or f"PX-{uuid.uuid4().hex[:8].upper()}"
    with get_conn() as conn:
        existing = conn.execute("SELECT pattern_id FROM recon_pattern_registry WHERE pattern_id=?", (pattern_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Pattern ID already exists")
        conn.execute(
            """
            INSERT INTO recon_pattern_registry
            (pattern_id, pattern_name, pattern_type, pattern_rule_json, status, execution_mode, confidence_threshold, approved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_id,
                request.pattern_name,
                request.pattern_type,
                json_dumps(request.pattern_rule),
                request.status,
                request.execution_mode,
                request.confidence_threshold,
                request.approved_by,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM recon_pattern_registry WHERE pattern_id=?", (pattern_id,)).fetchone()
    return row_to_dict(row)

@app.patch("/api/patterns/{pattern_id}")
def update_pattern(pattern_id: str, request: PatternUpdateRequest) -> dict:
    fields = []
    params = []
    data = request.model_dump(exclude_unset=True)
    if "pattern_rule" in data:
        data["pattern_rule_json"] = json_dumps(data.pop("pattern_rule"))
    for field in ["pattern_name", "pattern_type", "pattern_rule_json", "status", "execution_mode", "confidence_threshold", "approved_by"]:
        if field in data and data[field] is not None:
            fields.append(f"{field}=?")
            params.append(data[field])
    if not fields:
        raise HTTPException(status_code=400, detail="No fields supplied for update")
    params.append(pattern_id)
    with get_conn() as conn:
        existing = conn.execute("SELECT pattern_id FROM recon_pattern_registry WHERE pattern_id=?", (pattern_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Pattern not found")
        conn.execute(f"UPDATE recon_pattern_registry SET {', '.join(fields)} WHERE pattern_id=?", params)
        conn.commit()
        row = conn.execute("SELECT * FROM recon_pattern_registry WHERE pattern_id=?", (pattern_id,)).fetchone()
    rerun_reconciliation_only()
    return row_to_dict(row)

@app.post("/api/patterns/{pattern_id}/activate")
def activate_pattern(pattern_id: str) -> dict:
    return update_pattern(pattern_id, PatternUpdateRequest(status="ACTIVE"))

@app.post("/api/patterns/{pattern_id}/deactivate")
def deactivate_pattern(pattern_id: str) -> dict:
    return update_pattern(pattern_id, PatternUpdateRequest(status="INACTIVE"))

@app.get("/api/pattern-candidates")
def list_pattern_candidates() -> dict:
    with get_conn() as conn: rows=rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_candidate ORDER BY created_at DESC").fetchall())
    return {"items":rows}

@app.post("/api/learning/demo-signals")
def create_demo_signals() -> dict:
    return seed_demo_learning_signals()

@app.post("/api/learning/run")
def run_learning_job() -> dict:
    return run_learning()

@app.post("/api/pattern-candidates/{candidate_id}/approve")
def approve_pattern(candidate_id: str, request: CandidateApprovalRequest) -> dict:
    try: result=approve_candidate(candidate_id, request.approved_by, request.execution_mode, request.confidence_threshold)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    rerun_reconciliation_only()
    return result

