from __future__ import annotations
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import get_conn, init_db, json_dumps, row_to_dict, rows_to_dicts
from .learning import approve_candidate, run_learning, seed_demo_learning_signals
from .loader import load_samples_and_reconcile, rerun_reconciliation_only
from .schemas import CandidateApprovalRequest, CaseResolveRequest, ReconcileRunRequest, UserEventRequest

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

@app.post("/api/load-sample")
def load_sample(request: ReconcileRunRequest = ReconcileRunRequest()) -> dict:
    return load_samples_and_reconcile(amount_divisor=request.amount_divisor, reset=request.reset)

@app.post("/api/reconcile/run")
def run_reconcile() -> dict:
    return rerun_reconciliation_only()

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

