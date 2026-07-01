# TASK-49 · Backend — AI Verifier for static rule exception cases

**Type:** Backend  
**Branch:** `feat/ai-exception-verifier`  
**Depends on:** TASK-04 (Tier 2c LLM infrastructure must exist)  
**Blocks:** TASK-50  
**Effort:** ~4–5 hours

---

## Background

The current AI triage pipeline runs only on `Uncleared / In-Transit` cases — records Pass 1
left completely unmatched. But a significant volume of analyst work comes from **exception
cases that Pass 1 did match but flagged as uncertain**:

| Status | Rule | Analyst burden |
|---|---|---|
| `Suggested Match – Analyst Review` | P4 fuzzy (0.85–0.99) | Must judge whether the fuzzy hit is real |
| `Exception – Amount Variance Review` | P7 amount gap > threshold | Must decide if the variance is intentional |
| `Suggested Match – Enhanced Fuzzy` | P4b rapidfuzz | Same as P4 |

Today these land in the queue with no explanation beyond the rule code. The analyst has to
reason from scratch. This task adds an **AI Verifier** pass: for each exception case, the
LLM reviews the already-proposed PSR↔CAMT pair and answers:
*"Does this match look correct? What gives you confidence or concern?"*

This is fundamentally different from triage:
- **Triage**: AI searches for a candidate (many-to-one: 1 PSR vs N CAMTs)
- **Verifier**: AI reviews a specific pair (one-to-one: 1 PSR already matched to 1 CAMT)

The LLM output is stored as an `ai_verification` annotation in `feature_snapshot_json` —
it does NOT change the `reconciliation_status`. The status is set by the deterministic rule;
AI annotates with a second opinion.

---

## Acceptance Criteria

- [ ] New function `verify_exception_cases(case_ids=None)` added to `backend/app/ai_triage.py`
- [ ] Function fetches exception cases (optionally filtered to specific `case_ids`)
- [ ] For each case, builds a focused LLM prompt: "Rule X proposed this PSR↔CAMT pair.
      Review the identity signals and state whether this match looks correct."
- [ ] LLM response is a structured JSON: `{verdict, confidence_pct, note}` where:
  - `verdict`: `"AGREE"` | `"CAUTION"` | `"DISAGREE"`
  - `confidence_pct`: integer 0–100
  - `note`: one sentence (max 20 words) stating the reason
- [ ] Result is merged into the existing `feature_snapshot_json` under a new
      `"ai_verification"` key — existing snapshot content is preserved
- [ ] New endpoint `POST /api/reconcile/ai-verify` added to `backend/app/main.py`
  - Optional body: `{"case_ids": ["CASE-000001", ...]}` (omit to run on all exception cases)
  - Returns `{"status": "ok", "verified_count": N}`
- [ ] If no LLM API key is configured, endpoint returns gracefully with
      `{"status": "skipped", "reason": "no_api_key"}`
- [ ] Concurrent execution via `ThreadPoolExecutor` (same pattern as `run_tier2c`)

---

## Files to Change

| File | Change |
|---|---|
| `backend/app/ai_triage.py` | New `verify_exception_cases()` function |
| `backend/app/main.py` | New `POST /api/reconcile/ai-verify` endpoint |

---

## Exception Case Target Statuses

```python
VERIFIABLE_STATUSES = [
    "Suggested Match – Analyst Review",       # P4 fuzzy
    "Suggested Match – Enhanced Fuzzy",       # P4b rapidfuzz
    "Exception – Amount Variance Review",     # P7 amount gap
]
```

---

## Implementation

### New function in `ai_triage.py`

```python
def verify_exception_cases(case_ids: Optional[List[str]] = None) -> List[Dict]:
    """
    AI second-opinion pass for exception cases produced by static rules.
    For each case, passes the existing PSR↔CAMT pair to the LLM and asks
    whether the match looks correct, returning AGREE / CAUTION / DISAGREE.
    Updates feature_snapshot_json with the ai_verification annotation.
    Does NOT change reconciliation_status.
    """
    import json, os, concurrent.futures
    from .config import settings

    VERIFIABLE_STATUSES = [
        "Suggested Match – Analyst Review",
        "Suggested Match – Enhanced Fuzzy",
        "Exception – Amount Variance Review",
    ]

    with get_conn() as conn:
        if case_ids:
            placeholders = ",".join("?" * len(case_ids))
            rows = rows_to_dicts(conn.execute(
                f"SELECT * FROM recon_cases WHERE case_id IN ({placeholders})",
                case_ids,
            ).fetchall())
        else:
            status_placeholders = ",".join("?" * len(VERIFIABLE_STATUSES))
            rows = rows_to_dicts(conn.execute(
                f"""SELECT * FROM recon_cases
                    WHERE reconciliation_status IN ({status_placeholders})
                      AND psr_id IS NOT NULL AND psr_id != ''
                      AND camt_id IS NOT NULL AND camt_id != ''""",
                VERIFIABLE_STATUSES,
            ).fetchall())

    if not rows:
        return []

    # ... (LLM call per case, same pattern as run_tier2c) ...
    # See "Prompt structure" section below
```

### Prompt structure

The prompt is simpler than triage — one pair, not a candidate list:

```
System:
You are a cash reconciliation auditor. A deterministic rule has proposed a match
between a PSR payment record and a bank CAMT entry.
Your job: review the IDENTITY signals and give a second opinion.
Focus only on whether these two records describe the same real-world payment.
Do NOT re-examine amount or date — those were checked by the rule already.

Return raw JSON only:
{"verdict": "AGREE|CAUTION|DISAGREE", "confidence_pct": 0-100, "note": "string"}
- AGREE: identity signals clearly support the match
- CAUTION: some overlap but signals are ambiguous or mixed
- DISAGREE: identity signals suggest these are different payments
Max 20 words in note.

User:
Rule applied: {rule_applied} (confidence {match_confidence}%)

PSR:
- ID: {psr_id}
- Reference: {reference}
- Invoice: {invoice}
- Counterparty: {counterparty}

CAMT:
- ID: {camt_id}
- PMT Reference: {camt_pmt_ref}
- Invoice: {camt_invoice}
- Counterparty: {camt_counterparty}
- Remittance: {camt_remittance}
```

### Updating `feature_snapshot_json`

Merge the verification result into the existing snapshot, preserving all prior content:

```python
with get_conn() as conn:
    existing_raw = conn.execute(
        "SELECT feature_snapshot_json FROM recon_cases WHERE case_id = ?",
        (case["case_id"],),
    ).fetchone()
    existing = json.loads(existing_raw[0] or "{}") if existing_raw else {}
    existing["ai_verification"] = {
        "verdict": result["verdict"],
        "confidence_pct": result.get("confidence_pct"),
        "note": result.get("note", ""),
        "verified_at": datetime.utcnow().isoformat(),
    }
    conn.execute(
        "UPDATE recon_cases SET feature_snapshot_json = ?, updated_at = CURRENT_TIMESTAMP WHERE case_id = ?",
        (json_dumps(existing), case["case_id"]),
    )
    conn.commit()
```

### New endpoint in `main.py`

```python
class AiVerifyRequest(BaseModel):
    case_ids: Optional[List[str]] = None

@app.post("/api/reconcile/ai-verify")
def run_ai_verify(body: AiVerifyRequest = None) -> dict:
    """AI second-opinion pass for static-rule exception cases."""
    from .ai_triage import verify_exception_cases
    case_ids = (body.case_ids if body else None)
    results = verify_exception_cases(case_ids=case_ids)
    return {"status": "ok", "verified_count": len(results)}
```

---

## Verification

1. Run full reconcile — ensure P4 / P7 exception cases exist
2. `POST /api/reconcile/ai-verify` (no body)
3. Query the DB:
   ```sql
   SELECT case_id, reconciliation_status,
          json_extract(feature_snapshot_json, '$.ai_verification.verdict') AS verdict,
          json_extract(feature_snapshot_json, '$.ai_verification.note') AS note
   FROM recon_cases
   WHERE json_extract(feature_snapshot_json, '$.ai_verification') IS NOT NULL;
   ```
4. Confirm `reconciliation_status` is unchanged (AI annotates only — does not override)
5. Confirm `ai_verification` present with `verdict`, `confidence_pct`, `note`
