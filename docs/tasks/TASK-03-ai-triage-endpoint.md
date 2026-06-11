# TASK-03 · Add `POST /api/reconcile/ai-triage` endpoint

**Type:** Backend  
**Branch:** `feature/residual-match-ai`  
**Depends on:** TASK-02 (`ai_triage.py` with `run_tier2b()` must exist)  
**Blocks:** TASK-04, TASK-05, TASK-06, TASK-07  
**Effort:** ~2–3 hours

---

## Background

The AI triage logic lives in `ai_triage.py` (TASK-02). This task wires it to a FastAPI endpoint so the frontend can trigger it and so the results are persisted into `recon_cases` as `AI_SUGGESTED` status records.

This is the integration point between the AI module and the rest of the system.

---

## Acceptance Criteria

- [ ] `POST /api/reconcile/ai-triage` endpoint exists and returns HTTP 200 with a result summary
- [ ] Calling the endpoint runs `run_tier2b()` and writes `AI_SUGGESTED` cases to `recon_cases`
- [ ] "Clear" matches (cosine ≥ 0.85) are inserted as `"AI-Assisted Suggested Match"` status
- [ ] "Maybe" zone records (0.60–0.84) are also inserted but with status `"AI - Analyst Adjudication Required"` and passed to Tier 2c (TASK-04) once it exists
- [ ] Response body contains `{ inserted_count, clear_count, maybe_count, skipped_count }`
- [ ] Endpoint is idempotent — calling it twice does not duplicate cases (use `INSERT OR REPLACE` or clear previous `AI_SUGGESTED` cases first)
- [ ] Endpoint is documented in `README.md` API list

---

## Implementation

### Step 1 — Add import to `backend/app/main.py`

Near the top of `main.py` where other app modules are imported:
```python
from .ai_triage import run_tier2b
```

### Step 2 — Add the endpoint to `backend/app/main.py`

Add after the existing `/api/reconcile/run` endpoint:

```python
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
        # Remove any previous AI suggestions so reruns are clean
        conn.execute(
            "DELETE FROM recon_cases WHERE reconciliation_status LIKE 'AI%'"
        )

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
                    json.dumps([{
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
                    json.dumps([{
                        "action": "ROUTE_TO_ANALYST",
                        "confidence": c["cosine_score"],
                        "tier": "2b_maybe",
                        "camt_id": c["camt_id"],
                    }]),
                )
            )
            inserted += 1

        conn.commit()

    return {
        "status": "ok",
        "inserted_count": inserted,
        "clear_count": len(clear),
        "maybe_count": len(maybe),
        "skipped_count": len(candidates) - len(clear) - len(maybe),
    }
```

Note: `json` is already imported in `main.py`. Confirm with a quick grep before adding a duplicate import.

### Step 3 — Update `README.md`

Add to the Reconciliation API section:
```
POST /api/reconcile/ai-triage
```

### Step 4 — Manual test via FastAPI docs

1. Start the backend: `uvicorn app.main:app --reload --port 8090`
2. Load sample data via the UI (Control Room → Load sample PSR/CAMT)
3. Open `http://localhost:8090/docs`
4. POST `/api/reconcile/ai-triage` with no body
5. Verify response contains `inserted_count > 0`
6. GET `/api/reconcile/cases` and filter for `AI_SUGGESTED` status records

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/main.py` | Add import of `run_tier2b`; add `POST /api/reconcile/ai-triage` endpoint |
| `README.md` | Add new endpoint to API list |

---

## Notes

- The `DELETE FROM recon_cases WHERE reconciliation_status LIKE 'AI%'` makes the endpoint idempotent — safe to call multiple times.
- Once TASK-04 is complete, the `maybe` zone records will be passed through Tier 2c within the same endpoint call (LLM adjudication updates those rows in place).
- POC limitation: all AI cases are wiped when the user clicks "Run reconciliation" (the deterministic rerun clears `recon_cases`). This is acceptable for the POC — see FS-5 in `AI_TRIAGE_PLAN.md` for the production solution.
