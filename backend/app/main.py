from __future__ import annotations
import uuid
from typing import Optional
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import get_conn, init_db, json_dumps, row_to_dict, rows_to_dicts
from .learning import approve_candidate, run_learning, seed_demo_learning_signals
from .ingestion import get_batch, list_batches, run_uploaded_batch, store_uploaded_file
from .loader import load_samples_and_reconcile, rerun_reconciliation_only
from .quality import get_quality_report, validate_batch
from .workflow import get_exception_workflow, list_exception_workflow, mark_workflow_resolved, update_exception_workflow
from .workspace import create_snapshot, export_reconciliation_results, get_dashboard_model, get_data_preview, get_no_code_rules, get_workspace_overview, get_workflow_rules, list_submissions, predict_match_fields
from .schemas import CandidateApprovalRequest, CaseResolveRequest, PatternCreateRequest, PatternUpdateRequest, ReconcileRunRequest, UserEventRequest, WorkflowUpdateRequest
from .ai_triage import run_tier2b, run_tier2c

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup() -> None:
    init_db()
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases").fetchone()["cnt"]
    if existing == 0:
        load_samples_and_reconcile(reset=True)

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

@app.post("/api/reconcile/ai-triage")
def run_ai_triage() -> dict:
    """
    Pass 2 AI residual triage.
    Tier 2b: embedding similarity on unmatched PSR pool.
    Stores AI_SUGGESTED cases in recon_cases.
    Tier 2c (LLM adjudication) runs automatically for 'maybe' zone records
    once TASK-04 is implemented.
    """
    candidates = run_tier2b()

    clear = [c for c in candidates if c["zone"] == "clear"]
    maybe = [c for c in candidates if c["zone"] == "maybe"]

    inserted = 0
    with get_conn() as conn:
        # Remove previous AI suggestions so reruns are idempotent
        conn.execute("DELETE FROM recon_cases WHERE reconciliation_status LIKE 'AI%'")

        for c in clear:
            case_id = f"AI-{c['psr_id']}-{c['camt_id']}"
            conf = int(c["cosine_score"] * 100)
            conn.execute(
                """INSERT OR REPLACE INTO recon_cases
                   (case_id, psr_id, camt_id, reconciliation_status, reason_code,
                    match_type, match_confidence, rule_applied, exception_flag,
                    explanation, suggestions_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (
                    case_id,
                    c["psr_id"],
                    c["camt_id"],
                    "AI-Assisted Suggested Match",
                    "AI_EMBEDDING_MATCH",
                    "1_TO_1",
                    conf,
                    "TIER2B_EMBEDDING",
                    "Y",
                    f"Embedding cosine similarity {c['cosine_score']:.4f}. "
                    f"PSR text: '{c['psr_text']}'. CAMT text: '{c['camt_text']}'.",
                    json_dumps([{
                        "action": "CONFIRM_AI_MATCH",
                        "confidence": c["cosine_score"],
                        "tier": "2b",
                        "camt_id": c["camt_id"],
                    }]),
                )
            )
            inserted += 1

        for c in maybe:
            case_id = f"AI-MAYBE-{c['psr_id']}-{c['camt_id']}"
            conf = int(c["cosine_score"] * 100)
            conn.execute(
                """INSERT OR REPLACE INTO recon_cases
                   (case_id, psr_id, camt_id, reconciliation_status, reason_code,
                    match_type, match_confidence, rule_applied, exception_flag,
                    explanation, suggestions_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (
                    case_id,
                    c["psr_id"],
                    c["camt_id"],
                    "AI - Analyst Adjudication Required",
                    "AI_MAYBE_ZONE",
                    "1_TO_1",
                    conf,
                    "TIER2B_EMBEDDING",
                    "Y",
                    f"Embedding similarity {c['cosine_score']:.4f} — in 'maybe' zone (0.60–0.84). "
                    f"Awaiting LLM adjudication (Tier 2c).",
                    json_dumps([{
                        "action": "ROUTE_TO_ANALYST",
                        "confidence": c["cosine_score"],
                        "tier": "2b_maybe",
                        "camt_id": c["camt_id"],
                    }]),
                )
            )
            inserted += 1

        conn.commit()

    llm_decisions = run_tier2c(maybe)

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
    return {"case":row_to_dict(row),"events":events,"manual_resolutions":resolutions}


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

@app.post("/api/reconcile/cases/{case_id}/resolve")
def resolve_case(case_id: str, request: CaseResolveRequest) -> dict:
    with get_conn() as conn:
        case=conn.execute("SELECT * FROM recon_cases WHERE case_id=?", (case_id,)).fetchone()
        if not case: raise HTTPException(status_code=404, detail="Case not found")
        event_id=f"EVT-{uuid.uuid4().hex[:10].upper()}"; resolution_id=f"RES-{uuid.uuid4().hex[:10].upper()}"
        selected_psr=request.selected_psr_ids or ([case["psr_id"]] if case["psr_id"] else [])
        selected_bank=request.selected_bank_ids or ([case["camt_id"]] if case["camt_id"] else [])
        payload={"case_id":case_id,"resolution_type":request.resolution_type,"reason_code":request.reason_code,"selected_psr_ids":selected_psr,"selected_bank_ids":selected_bank,"fields_used":request.fields_used,"fields_ignored":request.fields_ignored,"accepted_variance":request.accepted_variance,"comment":request.comment,"previous_engine_confidence":case["match_confidence"],"final_user_confidence":request.final_user_confidence}
        conn.execute("INSERT INTO recon_user_action_event (event_id, case_id, event_type, user_id, event_payload_json) VALUES (?, ?, 'exception_resolved', 'prototype_user', ?)", (event_id,case_id,json_dumps(payload)))
        conn.execute("INSERT INTO recon_manual_resolution (resolution_id, case_id, original_exception_type, final_resolution_type, reason_code, psr_transaction_ids_json, bank_transaction_ids_json, amount_variance, date_variance_days, fields_used_json, fields_ignored_json, user_comment, resolved_by, learning_eligible) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prototype_user', ?)", (resolution_id,case_id,case["reconciliation_status"],request.resolution_type,request.reason_code,json_dumps(selected_psr),json_dumps(selected_bank),request.accepted_variance if request.accepted_variance is not None else case["variance"],case["aging_days"],json_dumps(request.fields_used),json_dumps(request.fields_ignored),request.comment,1 if request.learning_eligible else 0))
        conn.execute("UPDATE recon_cases SET reconciliation_status='Resolved Manually', reason_code=?, exception_flag='N', explanation=?, updated_at=CURRENT_TIMESTAMP WHERE case_id=?", (request.reason_code,f"Resolved by analyst as {request.resolution_type}. Learning signal captured.",case_id))
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

