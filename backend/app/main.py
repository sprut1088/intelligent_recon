from __future__ import annotations
import csv, io, json, logging, re, time, uuid
from typing import List, Optional
import tempfile
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from .config import settings
from .db import get_conn, init_db, json_dumps, row_to_dict, rows_to_dicts
from .learning import approve_candidate, run_learning, seed_demo_learning_signals
from .filepatternrecognition import generate_mapping_regex, generate_reconciliation_patterns, recognize_files, _write_upload_to_temp, suggest_patterns_for_unmatched, compare_patterns_with_llm
from .ingestion import get_batch, list_batches, run_uploaded_batch, store_uploaded_file
from .loader import load_samples_and_reconcile, rerun_reconciliation_only
from .quality import get_quality_report, validate_batch
from .workflow import get_exception_workflow, list_exception_workflow, mark_workflow_resolved, update_exception_workflow
from .workspace import create_snapshot, export_reconciliation_results, get_dashboard_model, get_data_preview, get_no_code_rules, get_workspace_overview, get_workflow_rules, list_submissions, predict_match_fields
from .schemas import BulkPatternSaveRequest, PatternCompareRequest, AiVerifyRequest, CandidateApprovalRequest, CaseResolveRequest, PatternCreateRequest, PatternUpdateRequest, ReconcileRunRequest, UserEventRequest, WorkflowUpdateRequest
from .ai_triage import build_ai_snapshot, find_candidates, run_tier2c, verify_exception_cases

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

@app.post("/api/files/recognize-patterns")
def recognize_file_patterns(
    camt_file: UploadFile = File(...),
    other_file: UploadFile = File(...),
) -> dict:
    try:
        return recognize_files(camt_file, other_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/files/generate-mapping")
def generate_file_mapping(
    camt_file: UploadFile = File(...),
    other_file: UploadFile = File(...),
    max_examples: int = Form(10),
) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        camt_path = _write_upload_to_temp(camt_file, temp_dir_path)
        other_path = _write_upload_to_temp(other_file, temp_dir_path)
        try:
            return generate_mapping_regex(camt_path, other_path, max_examples=max_examples)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/files/reconcile-patterns")
def generate_reconciliation_patterns_route(
    camt_file: UploadFile = File(...),
    other_file: UploadFile = File(...),
    provided_regex_map: Optional[str] = Form(None),
) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        camt_path = _write_upload_to_temp(camt_file, temp_dir_path)
        other_path = _write_upload_to_temp(other_file, temp_dir_path)
        try:
            regex_map = None
            if provided_regex_map:
                import json
                regex_map = json.loads(provided_regex_map)
            return generate_reconciliation_patterns(camt_path, other_path, provided_regex_map=regex_map)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON for provided_regex_map: {exc}") from exc


@app.post("/api/files/pattern-suggestions")
def generate_pattern_suggestions(
    camt_file: UploadFile = File(...),
    other_file: UploadFile = File(...),
    max_examples: int = Form(8),
) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        camt_path = _write_upload_to_temp(camt_file, temp_dir_path)
        other_path = _write_upload_to_temp(other_file, temp_dir_path)
        try:
            return suggest_patterns_for_unmatched(camt_path, other_path, max_examples=max_examples)
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
        return run_uploaded_batch(
            batch_id,
            amount_divisor=request.amount_divisor,
            reset_transactions=request.reset,
            pattern_group=request.pattern_group,
        )
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



# All AI candidates start as 'Adjudication Required' pending the LLM decision.
# Tier 2c overwrites this to the final status (CONFIRM / ROUTE / NO_MATCH).
_AI_PENDING = {
    "prefix": "AI",
    "status": "AI - Analyst Adjudication Required",
    "reason_code": "AI_PENDING_LLM",
    "suggestion_action": "ROUTE_TO_ANALYST",
    "tier_label": "2b_domain",
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


@app.post("/api/reconcile/ai-verify")
def run_ai_verify(body: AiVerifyRequest = None) -> dict:
    """AI second-opinion pass for static-rule exception cases."""
    case_ids = body.case_ids if body else None
    results = verify_exception_cases(case_ids=case_ids)
    return {"status": "ok", "verified_count": len(results)}


@app.post("/api/reconcile/ai-pass")
def run_ai_pass() -> dict:
    """
    Combined AI full pass: triage unmatched PSRs then verify exception cases.
    Equivalent to calling ai-triage followed by ai-verify in sequence.
    Returns combined stats: {triaged_count, verified_count}.
    """
    logger.info("AI full pass requested")
    # Phase 1 — triage (reuses same logic as /ai-triage endpoint)
    triage_result = run_ai_triage()
    triaged = triage_result.get("inserted_count", 0)
    logger.info("AI full pass: triage complete — %d candidates inserted", triaged)
    # Phase 2 — verify exception cases
    verify_results = verify_exception_cases()
    verified = len(verify_results)
    logger.info("AI full pass: verify complete — %d cases annotated", verified)
    return {"status": "ok", "triaged_count": triaged, "verified_count": verified}


@app.post("/api/reconcile/ai-triage")
def run_ai_triage() -> dict:
    """
    Pass 2 AI residual triage.
    Tier 2b: domain-aware candidate scoring (rapidfuzz + substring checks).
    Tier 2c: LLM adjudication for ALL candidates — LLM is the sole decision-maker.
    """
    logger.info("AI triage requested")
    candidates = find_candidates()
    logger.info("Tier 2b complete: %d candidates found", len(candidates))

    # Group by PSR — find_candidates returns up to 5 per PSR sorted by score desc.
    # We insert exactly ONE row per PSR (the top candidate); alternatives are
    # stored in suggestions_json so the analyst can see them in the drawer.
    by_psr: dict = {}
    for c in candidates:
        pid = c["psr_id"]
        if pid not in by_psr:
            by_psr[pid] = []
        by_psr[pid].append(c)

    inserted = 0
    with get_conn() as conn:
        # Remove previous AI rows so reruns are idempotent.
        conn.execute("DELETE FROM recon_cases WHERE case_id LIKE 'AI%'")

        for psr_id_key, psr_candidates in by_psr.items():
            c = psr_candidates[0]          # top-scored candidate
            alternatives = psr_candidates[1:]  # remaining alternatives
            case_id = f"{_AI_PENDING['prefix']}-{c['psr_id']}-{c['camt_id']}"
            conf = int(c["candidate_score"] * 100)
            internal_amt = c.get("psr_amount")
            bank_amt = c.get("camt_amount")
            variance = (
                round(float(internal_amt) - float(bank_amt), 2)
                if internal_amt is not None and bank_amt is not None
                else None
            )
            explanation = (
                f"Domain score {c['candidate_score']:.4f}. "
                f"Awaiting LLM adjudication (Tier 2c)."
            )
            suggestions = [{
                "action": _AI_PENDING["suggestion_action"],
                "confidence": c["candidate_score"],
                "tier": _AI_PENDING["tier_label"],
                "camt_id": c["camt_id"],
            }] + [
                {
                    "action": "ALTERNATIVE",
                    "confidence": alt["candidate_score"],
                    "tier": _AI_PENDING["tier_label"],
                    "camt_id": alt["camt_id"],
                }
                for alt in alternatives
            ]
            conn.execute(_AI_CASE_INSERT_SQL, (
                case_id, c["psr_id"], c["camt_id"],
                _AI_PENDING["status"], _AI_PENDING["reason_code"], "1_TO_1",
                conf, "AI_DOMAIN_SCORED", "Y",
                explanation,
                json_dumps(suggestions),
                json_dumps(build_ai_snapshot(c, conf, "AI_DOMAIN_SCORED")),
                c.get("psr_reference") or c.get("camt_pmt_ref"),
                c.get("psr_invoice") or c.get("camt_invoice"),
                c.get("psr_counterparty") or c.get("camt_counterparty"),
                internal_amt, bank_amt, variance,
                c.get("psr_currency") or c.get("camt_currency") or "EUR",
                c.get("psr_execution_date") or "",
                c.get("camt_booking_date") or "",
            ))
            inserted += 1

        # Remove the original Uncleared / In-Transit rows for PSRs that now
        # have an AI candidate row — otherwise In-Transit count never decreases.
        if by_psr:
            placeholders = ",".join("?" * len(by_psr))
            conn.execute(
                f"""DELETE FROM recon_cases
                    WHERE psr_id IN ({placeholders})
                      AND reconciliation_status IN (
                          'Uncleared / In-Transit Payment'
                      )
                      AND case_id NOT LIKE 'AI%'""",
                list(by_psr.keys()),
            )

        conn.commit()

    llm_decisions = run_tier2c(candidates)
    logger.info(
        "AI triage complete: psr_groups=%d inserted=%d llm_adjudicated=%d",
        len(by_psr), inserted, len(llm_decisions),
    )

    # When AI claims a CAMT (CONFIRM or ROUTE_TO_ANALYST), the corresponding
    # Bank-only row for that CAMT is now redundant — the CAMT is no longer
    # unmatched. Delete those Bank-only rows so the count reflects reality.
    # NO_MATCH decisions are excluded: if AI found no PSR for the CAMT,
    # the Bank-only row should stay.
    claimed_camt_ids = [
        d["matched_camt_id"]
        for d in llm_decisions
        if d.get("suggested_action") in ("CONFIRM_AI_MATCH", "ROUTE_TO_ANALYST")
        and d.get("matched_camt_id")
    ]
    if claimed_camt_ids:
        with get_conn() as conn:
            placeholders = ",".join("?" * len(claimed_camt_ids))
            conn.execute(
                f"""DELETE FROM recon_cases
                    WHERE camt_id IN ({placeholders})
                      AND reconciliation_status = 'Bank-only Item - Investigation'""",
                claimed_camt_ids,
            )
            conn.commit()
        logger.info("Removed %d Bank-only rows whose CAMT is now AI-claimed", len(claimed_camt_ids))

    return {
        "status": "ok",
        "candidates_count": len(candidates),
        "inserted_count": inserted,
        "llm_adjudicated_count": len(llm_decisions),
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
        kpi=row_to_dict(conn.execute("SELECT COALESCE(SUM(COALESCE(internal_amount,0)),0) AS internal_amount, COALESCE(SUM(COALESCE(bank_amount,0)),0) AS bank_amount, COALESCE(SUM(ABS(COALESCE(variance,0))),0) AS absolute_variance, COALESCE(AVG(match_confidence),0) AS average_confidence, SUM(CASE WHEN exception_flag='Y' THEN 1 ELSE 0 END) AS exception_count, SUM(CASE WHEN reconciliation_status LIKE 'Matched%' OR reconciliation_status = 'Resolved Manually' THEN 1 ELSE 0 END) AS auto_matched_count, SUM(CASE WHEN json_extract(feature_snapshot_json, '$.ai_verification') IS NOT NULL AND rule_applied NOT LIKE 'TIER2C%' THEN 1 ELSE 0 END) AS ai_verified_count FROM recon_cases").fetchone())
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

@app.get("/api/reconcile/cases/export")
def export_cases(
    status: Optional[str] = None,
    exception_only: bool = False,
    search: Optional[str] = None,
    group_id: Optional[str] = None,
    filename: Optional[str] = None,
) -> StreamingResponse:
    clauses=[]; params=[]
    if group_id: clauses.append("group_id = ?"); params.append(group_id)
    if status == 'ai_processed':
        clauses.append("reconciliation_status IN ('AI-Assisted Suggested Match', 'AI - Analyst Adjudication Required', 'AI Confirmed \u2014 No Match')")
    elif status == 'in_transit':
        clauses.append("reconciliation_status IN ('Uncleared / In-Transit Payment', 'AI Confirmed \u2014 No Match')")
    elif status == 'matched':
        clauses.append("reconciliation_status IN ('Matched & Settled (Auto-Close)', 'Resolved Manually')")
    elif status in ('ai_agree', 'ai_caution', 'ai_disagree'):
        clauses.append("json_extract(feature_snapshot_json, '$.ai_verification.verdict') = ?")
        params.append(status.split('_', 1)[1].upper())
    elif status: clauses.append("reconciliation_status = ?"); params.append(status)
    if exception_only: clauses.append("exception_flag = 'Y' AND reconciliation_status NOT IN ('Uncleared / In-Transit Payment', 'Bank-only Item - Investigation', 'AI Confirmed \u2014 No Match')")
    if search:
        clauses.append("(case_id LIKE ? OR psr_id LIKE ? OR camt_id LIKE ? OR reference LIKE ? OR invoice LIKE ? OR counterparty LIKE ?)")
        term=f"%{search}%"; params.extend([term]*6)
    where="WHERE "+" AND ".join(clauses) if clauses else ""
    COLS = [
        "case_id","psr_id","camt_id","match_type","group_id","group_role",
        "reference","invoice","counterparty","internal_amount","bank_amount",
        "variance","currency","value_date","booking_date",
        "reconciliation_status","reason_code","match_confidence","rule_applied",
        "exception_flag","aging_days","aging_bucket","explanation",
    ]
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute(
            f"SELECT * FROM recon_cases {where} ORDER BY case_id", params
        ).fetchall())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    safe_filename = re.sub(r'[^\w\-]', '_', filename or 'recon_report') + '.csv'
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"},
    )

@app.get("/api/reconcile/cases")
def list_cases(status: Optional[str]=None, exception_only: bool=False, search: Optional[str]=None, group_id: Optional[str]=None, limit:int=Query(100,ge=1,le=1000), offset:int=Query(0,ge=0)) -> dict:
    clauses=[]; params=[]
    if group_id: clauses.append("group_id = ?"); params.append(group_id)
    if status == 'ai_processed':
        clauses.append("(reconciliation_status IN ('AI-Assisted Suggested Match', 'AI - Analyst Adjudication Required', 'AI Confirmed \u2014 No Match') OR (json_extract(feature_snapshot_json, '$.ai_verification') IS NOT NULL AND rule_applied NOT LIKE 'TIER2C%'))")
    elif status == 'in_transit':
        clauses.append("reconciliation_status IN ('Uncleared / In-Transit Payment', 'AI Confirmed \u2014 No Match')")
    elif status == 'matched':
        clauses.append("reconciliation_status IN ('Matched & Settled (Auto-Close)', 'Resolved Manually')")
    elif status in ('ai_agree', 'ai_caution', 'ai_disagree'):
        clauses.append("json_extract(feature_snapshot_json, '$.ai_verification.verdict') = ?")
        params.append(status.split('_', 1)[1].upper())
    elif status: clauses.append("reconciliation_status = ?"); params.append(status)
    if exception_only: clauses.append("exception_flag = 'Y' AND reconciliation_status NOT IN ('Uncleared / In-Transit Payment', 'Bank-only Item - Investigation', 'AI Confirmed \u2014 No Match')")
    if search:
        clauses.append("(case_id LIKE ? OR psr_id LIKE ? OR camt_id LIKE ? OR reference LIKE ? OR invoice LIKE ? OR counterparty LIKE ?)")
        term=f"%{search}%"; params.extend([term]*6)
    where="WHERE "+" AND ".join(clauses) if clauses else ""
    with get_conn() as conn:
        total=conn.execute(f"SELECT COUNT(*) AS cnt FROM recon_cases {where}", params).fetchone()["cnt"]
        rows=rows_to_dicts(conn.execute(f"SELECT * FROM recon_cases {where} ORDER BY exception_flag DESC, match_confidence ASC, case_id ASC LIMIT ? OFFSET ?", [*params,limit,offset]).fetchall())
    logger.info(
        "list_cases: status=%r exception_only=%s search=%r group_id=%r -> total=%d returned=%d (offset=%d limit=%d)",
        status, exception_only, search, group_id, total, len(rows), offset, limit,
    )
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
        case = conn.execute("SELECT * FROM recon_cases WHERE case_id=?", (case_id,)).fetchone()
        if not case: raise HTTPException(status_code=404, detail="Case not found")

        # ── PSR / bank IDs for the resolution record ─────────────────────
        # Prefer embedded members list (consolidated group model); fall back to
        # request body or the single case IDs (1:1 cases).
        psr_members_list  = json.loads(case["psr_members_json"])  if case["psr_members_json"]  else None
        camt_members_list = json.loads(case["camt_members_json"]) if case["camt_members_json"] else None

        selected_psr = (
            [m["psr_id"] for m in psr_members_list]  if psr_members_list
            else request.selected_psr_ids or ([case["psr_id"]] if case["psr_id"] else [])
        )
        selected_bank = (
            [m["camt_id"] for m in camt_members_list] if camt_members_list
            else request.selected_bank_ids or ([case["camt_id"]] if case["camt_id"] else [])
        )

        # ── Override + learning eligibility ──────────────────────────────
        is_override    = bool(request.override_reason)
        is_group_case  = (case["rule_applied"] or "").startswith(("P6_", "P10_"))
        effective_learning_eligible = False if (is_override or is_group_case) else request.learning_eligible
        effective_comment = request.comment
        if is_override:
            note_part = f" Note: {request.override_note}" if request.override_note else ""
            effective_comment = f"Override reason: {request.override_reason}.{note_part}"

        # ── Write event ───────────────────────────────────────────────────
        event_id      = f"EVT-{uuid.uuid4().hex[:10].upper()}"
        resolution_id = f"RES-{uuid.uuid4().hex[:10].upper()}"
        group_id      = case["group_id"]
        payload = {
            "case_id": case_id, "group_id": group_id,
            "resolution_type": request.resolution_type, "reason_code": request.reason_code,
            "selected_psr_ids": selected_psr, "selected_bank_ids": selected_bank,
            "fields_used": request.fields_used, "fields_ignored": request.fields_ignored,
            "accepted_variance": request.accepted_variance, "comment": effective_comment,
            "previous_engine_confidence": case["match_confidence"],
            "final_user_confidence": request.final_user_confidence,
            "override_reason": request.override_reason, "override_note": request.override_note,
        }
        conn.execute(
            "INSERT INTO recon_user_action_event (event_id, case_id, event_type, user_id, event_payload_json) VALUES (?, ?, 'exception_resolved', 'prototype_user', ?)",
            (event_id, case_id, json_dumps(payload)),
        )

        # ── One resolution row per case ───────────────────────────────────
        learning_signal_note = (
            "excluded (group engine suggestion)" if is_group_case
            else "excluded (override)" if is_override
            else "captured"
        )
        conn.execute(
            "INSERT INTO recon_manual_resolution (resolution_id, case_id, original_exception_type, final_resolution_type, reason_code, psr_transaction_ids_json, bank_transaction_ids_json, amount_variance, date_variance_days, fields_used_json, fields_ignored_json, user_comment, resolved_by, learning_eligible) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prototype_user', ?)",
            (resolution_id, case_id, case["reconciliation_status"], request.resolution_type,
             request.reason_code, json_dumps(selected_psr), json_dumps(selected_bank),
             request.accepted_variance if request.accepted_variance is not None else case["variance"],
             case["aging_days"], json_dumps(request.fields_used), json_dumps(request.fields_ignored),
             effective_comment, 1 if effective_learning_eligible else 0),
        )

        # ── Update this case ──────────────────────────────────────────────
        resolution_expl = f"Resolved by analyst as {request.resolution_type}. Learning signal {learning_signal_note}."
        conn.execute(
            "UPDATE recon_cases SET reconciliation_status='Resolved Manually', reason_code=?, exception_flag='N', explanation=?, updated_at=CURRENT_TIMESTAMP WHERE case_id=?",
            (request.reason_code, resolution_expl, case_id),
        )
        mark_workflow_resolved(conn, case_id, updated_by="prototype_user",
                               comment=f"Resolved as {request.resolution_type}")
        conn.commit()

    return {
        "case_id":      case_id,
        "event_id":     event_id,
        "resolution_id": resolution_id,
        "status":       "resolved",
        "group_id":     group_id,
    }

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

def _build_assistant_context() -> dict:
    """Gather a rich snapshot of live DB state for LLM/briefing consumption."""
    s = summary()
    total = s["total_cases"]
    kpi = s["kpi"]
    auto = int(kpi.get("auto_matched_count") or 0)
    ex = int(kpi.get("exception_count") or 0)
    variance = float(kpi.get("absolute_variance") or 0)
    avg_conf = float(kpi.get("average_confidence") or 0)
    match_rate = round((auto / total) * 100, 1) if total else 0
    learnt = s.get("learning_candidate_count", 0)

    with get_conn() as conn:
        # Top 5 open exceptions by absolute variance descending
        top_breaks = rows_to_dicts(conn.execute(
            """SELECT psr_id, camt_id, counterparty, internal_amount, bank_amount,
                      ABS(COALESCE(variance,0)) AS abs_var, reconciliation_status, rule_applied
               FROM recon_cases
               WHERE exception_flag='Y'
               ORDER BY abs_var DESC LIMIT 5"""
        ).fetchall())
        # AI triage counts
        ai_suggested = conn.execute(
            "SELECT COUNT(*) AS cnt FROM recon_cases WHERE reconciliation_status='AI-Assisted Suggested Match'"
        ).fetchone()["cnt"]
        ai_review = conn.execute(
            "SELECT COUNT(*) AS cnt FROM recon_cases WHERE reconciliation_status='AI - Analyst Adjudication Required'"
        ).fetchone()["cnt"]
        # Top rule by exception volume
        top_rule_row = conn.execute(
            """SELECT rule_applied, COUNT(*) AS cnt FROM recon_cases
               WHERE exception_flag='Y' GROUP BY rule_applied ORDER BY cnt DESC LIMIT 1"""
        ).fetchone()
        top_rule = dict(top_rule_row) if top_rule_row else {}
        # In-transit count
        in_transit = conn.execute(
            "SELECT COUNT(*) AS cnt FROM recon_cases WHERE reconciliation_status LIKE '%In-Transit%' OR reconciliation_status LIKE '%Uncleared%'"
        ).fetchone()["cnt"]

    return {
        "total_cases": total,
        "auto_closed": auto,
        "exceptions": ex,
        "match_rate_pct": match_rate,
        "average_confidence": round(avg_conf, 1),
        "absolute_variance_eur": round(variance, 2),
        "in_transit": in_transit,
        "learning_candidates": learnt,
        "ai_suggested": int(ai_suggested),
        "ai_review": int(ai_review),
        "top_breaks": top_breaks,
        "top_exception_rule": top_rule,
        "by_status": s.get("by_status", []),
        "by_rule": s.get("by_rule", []),
    }


def _context_to_text(ctx: dict) -> str:
    lines = [
        f"Total reconciliation cases: {ctx['total_cases']}",
        f"Auto-closed (matched): {ctx['auto_closed']} ({ctx['match_rate_pct']}% match rate)",
        f"Exceptions requiring action: {ctx['exceptions']}",
        f"In-transit / uncleared PSR items: {ctx['in_transit']}",
        f"Absolute variance: EUR {ctx['absolute_variance_eur']:,.2f}",
        f"Average match confidence: {ctx['average_confidence']}%",
        f"AI-suggested matches awaiting confirmation: {ctx['ai_suggested']}",
        f"AI records requiring analyst adjudication: {ctx['ai_review']}",
        f"Learned pattern candidates in governance inbox: {ctx['learning_candidates']}",
    ]
    if ctx.get("top_exception_rule"):
        lines.append(f"Most common exception rule: {ctx['top_exception_rule'].get('rule_applied')} ({ctx['top_exception_rule'].get('cnt')} cases)")
    if ctx.get("top_breaks"):
        lines.append("Top open breaks by amount:")
        for b in ctx["top_breaks"]:
            cp = b.get("counterparty") or b.get("psr_id") or "unknown"
            lines.append(f"  - {cp}: EUR {b.get('abs_var', 0):,.2f} | {b.get('reconciliation_status', '')}")
    return "\n".join(lines)


@app.get("/api/assistant/briefing")
def assistant_briefing() -> dict:
    """
    Auto-generated analyst briefing cards for the Copilot page.
    Returns a list of insight objects with title, body, severity and optional action.
    Uses LLM if OPENROUTER_API_KEY is set, otherwise falls back to rule-based insights.
    """
    import os
    ctx = _build_assistant_context()
    api_key = os.getenv("OPENROUTER_API_KEY", "")

    if api_key:
        import json as _json
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        system = (
            "You are an expert reconciliation operations assistant. "
            "Given a snapshot of the current reconciliation run, generate exactly 4 concise analyst briefing cards. "
            "Each card should highlight something actionable or noteworthy. "
            "Return valid JSON: an array of 4 objects each with keys: "
            "title (≤6 words), body (1-2 sentences), severity (info|warning|critical), "
            "action_label (≤4 words or null), action_tab (one of: results|exceptions|learning|governance or null)."
        )
        user = f"Current reconciliation state:\n{_context_to_text(ctx)}"
        try:
            resp = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=600,
            )
            raw = _json.loads(resp.choices[0].message.content)
            # Accept both {"insights": [...]} and a bare array
            insights = raw if isinstance(raw, list) else raw.get("insights") or raw.get("cards") or list(raw.values())[0]
            return {"insights": insights, "context": ctx, "source": "llm"}
        except Exception as exc:
            logger.warning("Briefing LLM call failed: %s — using rule-based fallback", exc)

    # Rule-based fallback
    insights = []
    if ctx["ai_suggested"] > 0:
        insights.append({"title": "AI matches need confirmation", "body": f"{ctx['ai_suggested']} AI-suggested match{'es' if ctx['ai_suggested'] != 1 else ''} are awaiting analyst confirmation in Results Workbench.", "severity": "warning", "action_label": "Review now", "action_tab": "results"})
    if ctx["ai_review"] > 0:
        insights.append({"title": "AI adjudication required", "body": f"{ctx['ai_review']} record{'s' if ctx['ai_review'] != 1 else ''} in the 'maybe' zone need analyst review before they can be closed.", "severity": "warning", "action_label": "Go to Results", "action_tab": "results"})
    if ctx["exceptions"] > 0:
        top = ctx["top_breaks"][0] if ctx["top_breaks"] else {}
        cp = top.get("counterparty") or "unknown counterparty"
        amt = top.get("abs_var", 0)
        insights.append({"title": "Open exception breaks", "body": f"{ctx['exceptions']} exception cases open. Largest break: EUR {amt:,.2f} · {cp}.", "severity": "critical" if ctx["exceptions"] > 10 else "warning", "action_label": "View exceptions", "action_tab": "exceptions"})
    if ctx["learning_candidates"] > 0:
        insights.append({"title": "Patterns ready for approval", "body": f"{ctx['learning_candidates']} learned pattern candidate{'s' if ctx['learning_candidates'] != 1 else ''} are awaiting governance approval in Learning Lab.", "severity": "info", "action_label": "Open Learning Lab", "action_tab": "learning"})
    if ctx["in_transit"] > 0:
        insights.append({"title": "In-transit items monitoring", "body": f"{ctx['in_transit']} PSR record{'s' if ctx['in_transit'] != 1 else ''} are uncleared or in-transit. Consider running AI triage to find matches.", "severity": "info", "action_label": "Run AI triage", "action_tab": "results"})
    if not insights:
        insights.append({"title": "Reconciliation healthy", "body": f"All {ctx['total_cases']} cases processed. Match rate {ctx['match_rate_pct']}% · no outstanding exceptions.", "severity": "info", "action_label": None, "action_tab": None})
    return {"insights": insights[:4], "context": ctx, "source": "rules"}


@app.get("/api/assistant/query")
def assistant_query(question: str) -> dict:
    """
    Free-text assistant query. Uses LLM (gpt-4o-mini via OpenRouter) if API key is
    set, otherwise falls back to keyword-based rule matching.
    Returns {question, answer, actions, source}.
    """
    import os
    ctx = _build_assistant_context()
    api_key = os.getenv("OPENROUTER_API_KEY", "")

    if api_key:
        import json as _json
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        system = (
            "You are Recon Copilot, an expert reconciliation operations assistant embedded in a cash reconciliation system. "
            "Answer the analyst's question based only on the provided reconciliation data snapshot. "
            "Be concise (2-4 sentences). Use specific numbers from the data. "
            "Also return 0-2 suggested follow-up actions as JSON. "
            "Return valid JSON with keys: answer (string), "
            "actions (array of {label: string ≤4 words, tab: one of results|exceptions|learning|governance})."
        )
        user = f"Reconciliation data snapshot:\n{_context_to_text(ctx)}\n\nAnalyst question: {question}"
        try:
            resp = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=400,
            )
            raw = _json.loads(resp.choices[0].message.content)
            return {"question": question, "answer": raw.get("answer", ""), "actions": raw.get("actions", []), "source": "llm", "context": ctx}
        except Exception as exc:
            logger.warning("Assistant LLM call failed: %s — using rule-based fallback", exc)

    # Rule-based fallback
    q = (question or "").lower()
    total = ctx["total_cases"]; auto = ctx["auto_closed"]; ex = ctx["exceptions"]
    match_rate = ctx["match_rate_pct"]; variance = ctx["absolute_variance_eur"]; learnt = ctx["learning_candidates"]
    actions = []
    if "exception" in q:
        answer = f"There are {ex} exception cases currently open. The most common exception rule is {ctx['top_exception_rule'].get('rule_applied', 'unknown')} with {ctx['top_exception_rule'].get('cnt', 0)} cases."
        actions = [{"label": "View exceptions", "tab": "exceptions"}]
    elif "auto" in q or "match rate" in q:
        answer = f"{auto} of {total} cases are auto-closed, giving a match rate of {match_rate}%."
        actions = [{"label": "View results", "tab": "results"}]
    elif "variance" in q:
        answer = f"The current absolute variance is EUR {variance:,.2f} across all reconciliation cases."
        actions = [{"label": "View exceptions", "tab": "exceptions"}]
    elif "learning" in q or "pattern" in q:
        answer = f"There are {learnt} learned-pattern candidates awaiting approval in the governance inbox."
        actions = [{"label": "Open Learning Lab", "tab": "learning"}]
    elif "ai" in q or "triage" in q:
        answer = f"{ctx['ai_suggested']} AI-suggested matches and {ctx['ai_review']} records requiring adjudication are currently in the system."
        actions = [{"label": "View AI results", "tab": "results"}]
    else:
        answer = f"Current run: {total} cases, {auto} auto-closed ({match_rate}% match rate), {ex} exceptions, EUR {variance:,.2f} total variance."
    return {"question": question, "answer": answer, "actions": actions, "source": "rules", "context": ctx}

def _group_patterns(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        group_name = (row.get("pattern_group") or "default").strip() or "default"
        grouped.setdefault(group_name, []).append(row)
    return [
        {
            "group_name": group_name,
            "items": sorted(items, key=lambda item: (item.get("pattern_name") or "").lower()),
        }
        for group_name, items in sorted(grouped.items(), key=lambda entry: entry[0].lower())
    ]


@app.get("/api/patterns")
def list_patterns() -> dict:
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM recon_pattern_registry ORDER BY pattern_id").fetchall())
    return {"items": rows, "grouped_patterns": _group_patterns(rows)}


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
            (pattern_id, pattern_name, pattern_type, pattern_group, pattern_version, pattern_rule_json, status, execution_mode, confidence_threshold, approved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_id,
                request.pattern_name,
                request.pattern_type,
                request.pattern_group,
                request.pattern_version,
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

@app.post("/api/patterns/bulk")
def create_bulk_patterns(request: BulkPatternSaveRequest) -> dict:
    """Save multiple patterns in one transaction, all assigned to *group_name*.

    Patterns are mapped from the file-analysis output format to the registry
    schema (fields_used → pattern_rule.fields, rule hints → execution_mode /
    confidence_threshold).  Existing pattern IDs are skipped without error.
    """
    if not request.group_name.strip():
        raise HTTPException(status_code=400, detail="group_name cannot be blank")
    created, skipped = [], []
    with get_conn() as conn:
        for p in request.patterns:
            pid = p.pattern_id or f"PX-{uuid.uuid4().hex[:8].upper()}"
            if conn.execute(
                "SELECT 1 FROM recon_pattern_registry WHERE pattern_id=?", (pid,)
            ).fetchone():
                skipped.append(pid)
                continue
            conn.execute(
                """
                INSERT INTO recon_pattern_registry
                (pattern_id, pattern_name, pattern_type, pattern_group,
                 pattern_version, pattern_rule_json, status, execution_mode,
                 confidence_threshold, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid, p.pattern_name, p.pattern_type,
                    request.group_name,   # always override with the bulk group
                    p.pattern_version,
                    json_dumps(p.pattern_rule), p.status,
                    p.execution_mode, p.confidence_threshold, p.approved_by,
                ),
            )
            created.append(pid)
        conn.commit()
    return {
        "created": len(created),
        "skipped": len(skipped),
        "pattern_ids": created,
        "group_name": request.group_name,
    }


@app.post("/api/patterns/compare")
def compare_patterns_route(request: PatternCompareRequest) -> dict:
    """LLM-powered comparison of identified patterns against a saved group."""
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute(
            "SELECT * FROM recon_pattern_registry WHERE pattern_group = ? AND status = 'ACTIVE'",
            (request.compare_group,)
        ).fetchall())
    if not rows:
        raise HTTPException(status_code=404, detail=f"Group '{request.compare_group}' has no active patterns")
    group_patterns = []
    for r in rows:
        try:
            r["pattern_rule"] = json.loads(r.get("pattern_rule_json") or "{}")
        except Exception:
            r["pattern_rule"] = {}
        group_patterns.append(r)
    identified = [p.model_dump() for p in request.identified_patterns]
    return compare_patterns_with_llm(identified, group_patterns, request.compare_group)


@app.patch("/api/patterns/{pattern_id}")
def update_pattern(pattern_id: str, request: PatternUpdateRequest) -> dict:
    fields = []
    params = []
    data = request.model_dump(exclude_unset=True)
    if "pattern_rule" in data:
        data["pattern_rule_json"] = json_dumps(data.pop("pattern_rule"))
    for field in ["pattern_name", "pattern_type", "pattern_group", "pattern_version", "pattern_rule_json", "status", "execution_mode", "confidence_threshold", "approved_by"]:
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

@app.delete("/api/patterns/{pattern_id}")
def delete_pattern(pattern_id: str) -> dict:
    with get_conn() as conn:
        existing = conn.execute("SELECT pattern_id FROM recon_pattern_registry WHERE pattern_id=?", (pattern_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Pattern not found")
        conn.execute("DELETE FROM recon_pattern_registry WHERE pattern_id=?", (pattern_id,))
        conn.commit()
    rerun_reconciliation_only()
    return {"pattern_id": pattern_id, "deleted": True}

@app.delete("/api/patterns/groups/{group_name}")
def delete_pattern_group(group_name: str) -> dict:
    with get_conn() as conn:
        result = conn.execute("SELECT COUNT(*) FROM recon_pattern_registry WHERE pattern_group=?", (group_name,)).fetchone()
        count = result[0] if result else 0
        if count == 0:
            raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found or is already empty")
        conn.execute("DELETE FROM recon_pattern_registry WHERE pattern_group=?", (group_name,))
        conn.commit()
    rerun_reconciliation_only()
    return {"group_name": group_name, "deleted_count": count}

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

