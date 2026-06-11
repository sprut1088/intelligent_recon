# TASK-04 · Extend `ai_triage.py` with Tier 2c — LLM adjudication for maybe-zone records

**Type:** Backend  
**Branch:** `feature/residual-match-ai`  
**Depends on:** TASK-02 (`ai_triage.py` exists), TASK-03 (endpoint exists to update)  
**Blocks:** Nothing — self-contained extension  
**Effort:** ~3–4 hours  
**Requires:** OpenAI API key (or compatible endpoint) in environment

---

## Background

Tier 2b (TASK-02) produces two buckets:
- **"clear"** (cosine ≥ 0.85) → stored directly as `AI-Assisted Suggested Match`
- **"maybe"** (0.60–0.84) → currently stored as `AI - Analyst Adjudication Required` but not further processed

Tier 2c takes the "maybe" zone records and sends each unmatched PSR with its **Top 5 CAMT candidates** to an LLM (GPT-4o-mini) for a focused adjudication question: *"Which of these 5 is the match, and why?"*

**Critical design constraints (from mentor review):**
1. One PSR + Top 5 candidates per LLM call — NOT a large N×M batch (LLMs get lost in large contexts)
2. Direction and date MUST be in the prompt (prevents January credit matching March debit)
3. Structured JSON output MUST be enforced via `response_format` — do not parse free text

---

## Acceptance Criteria

- [ ] `run_tier2c(candidates)` function added to `backend/app/ai_triage.py`
- [ ] Function accepts the "maybe" zone candidate list from `run_tier2b()`
- [ ] For each unique PSR in the maybe list, sends one LLM call with that PSR + its Top 5 candidates
- [ ] Prompt includes `direction`, `execution_date`/`booking_date`, `reference`, `invoice`, `counterparty`, `amount`, `currency`
- [ ] Response enforces JSON schema via `response_format={"type": "json_object"}`
- [ ] LLM responses update the existing `AI - Analyst Adjudication Required` cases in `recon_cases` with LLM confidence and reason
- [ ] If LLM returns `"NO_MATCH"`, case is updated to `"Uncleared / In-Transit Payment"` (falls back to P5)
- [ ] If `OPENAI_API_KEY` is not set, function logs a warning and returns without error (graceful degradation)
- [ ] TASK-03 endpoint updated to call `run_tier2c()` after `run_tier2b()`

---

## Implementation

### Step 1 — Add `openai` to `backend/requirements.txt`

```
openai>=1.30
```

Install:
```bash
pip install openai
```

### Step 2 — Add `run_tier2c()` to `backend/app/ai_triage.py`

Append to the existing file:

```python
def run_tier2c(maybe_candidates: List[Dict]) -> List[Dict]:
    """
    Tier 2c: LLM adjudication for 'maybe' zone records.

    For each unique PSR in maybe_candidates, sends one LLM call with
    that PSR + its Top 5 CAMT candidates. Updates recon_cases in-place.

    Returns list of LLM decision dicts.
    """
    import os
    import json

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        import logging
        logging.getLogger(__name__).warning(
            "OPENAI_API_KEY not set — Tier 2c LLM adjudication skipped."
        )
        return []

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    # Group candidates by PSR ID, keep Top 5 per PSR
    from collections import defaultdict
    by_psr: Dict[str, List[Dict]] = defaultdict(list)
    for c in maybe_candidates:
        by_psr[c["psr_id"]].append(c)
    for psr_id in by_psr:
        by_psr[psr_id] = sorted(by_psr[psr_id], key=lambda x: x["cosine_score"], reverse=True)[:5]

    # Fetch full PSR and CAMT rows for the prompt
    with get_conn() as conn:
        psr_map = {
            r["id"]: r for r in rows_to_dicts(
                conn.execute("SELECT * FROM psr_transactions").fetchall()
            )
        }
        camt_map = {
            r["camt_id"]: r for r in rows_to_dicts(
                conn.execute("SELECT * FROM camt_transactions").fetchall()
            )
        }

    decisions = []

    for psr_id, top_candidates in by_psr.items():
        psr = psr_map.get(psr_id)
        if not psr:
            continue

        candidate_lines = []
        for i, c in enumerate(top_candidates, 1):
            camt = camt_map.get(c["camt_id"])
            if not camt:
                continue
            candidate_lines.append(
                f"  {i}. ID:{camt['camt_id']} | Dir:{camt.get('direction','')} "
                f"| Amt:{camt.get('amount','')} {camt.get('currency','')} "
                f"| Date:{camt.get('booking_date','')} "
                f"| Party:{camt.get('counterparty','')} "
                f"| Remittance:{camt.get('remittance','')}"
            )

        if not candidate_lines:
            continue

        prompt = f"""You are a cash reconciliation analyst. One internal PSR payment record is unmatched.
Review the candidate bank (CAMT) entries below and identify the best match.

PSR:
  ID: {psr['id']} | Direction: {psr.get('direction','')} | Amount: {psr.get('amount','')} {psr.get('currency','')}
  Date: {psr.get('execution_date','')} | Reference: {psr.get('reference','')}
  Invoice: {psr.get('invoice','')} | Counterparty: {psr.get('counterparty','')}

CAMT Candidates (pre-filtered by amount/date/direction):
{chr(10).join(candidate_lines)}

Return valid JSON matching this schema exactly:
{{
  "psr_id": "string",
  "matched_camt_id": "string or null",
  "confidence_pct": number between 0 and 100,
  "reason": "one sentence explaining the match or why no match exists",
  "suggested_action": "CONFIRM_AI_MATCH or ROUTE_TO_ANALYST or NO_MATCH"
}}
If no candidate is a credible match, set matched_camt_id to null and suggested_action to NO_MATCH."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=300,
            )
            result = json.loads(response.choices[0].message.content)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Tier 2c LLM call failed for PSR {psr_id}: {e}")
            continue

        decisions.append(result)

        # Update the recon_case in DB
        with get_conn() as conn:
            if result.get("suggested_action") == "NO_MATCH":
                new_status = "Uncleared / In-Transit Payment"
                rule = "TIER2C_NO_MATCH"
            else:
                new_status = "AI-Assisted Suggested Match"
                rule = "TIER2C_LLM"

            conf = int(result.get("confidence_pct") or 0)
            reason_text = result.get("reason", "")
            matched_camt = result.get("matched_camt_id")

            # Update the most relevant existing case for this PSR
            conn.execute(
                """UPDATE recon_cases
                   SET reconciliation_status=?, match_confidence=?, rule_applied=?,
                       explanation=?, camt_id=COALESCE(?,camt_id),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE psr_id=? AND reconciliation_status='AI - Analyst Adjudication Required'
                   LIMIT 1""",
                (new_status, conf, rule, reason_text, matched_camt, psr_id)
            )
            conn.commit()

    return decisions
```

### Step 3 — Update `run_ai_triage()` endpoint in `main.py` (TASK-03)

After the existing `run_tier2b()` call, add:

```python
from .ai_triage import run_tier2b, run_tier2c   # update existing import

# Inside run_ai_triage():
    # ... after inserting maybe-zone cases ...
    llm_decisions = run_tier2c(maybe)
    # Update response:
    return {
        "status": "ok",
        "inserted_count": inserted,
        "clear_count": len(clear),
        "maybe_count": len(maybe),
        "llm_adjudicated_count": len(llm_decisions),
        "skipped_count": len(candidates) - len(clear) - len(maybe),
    }
```

### Step 4 — Set environment variable

Add to your local environment (or `.env` file — do NOT commit API keys):
```
OPENAI_API_KEY=sk-...
```

### Step 5 — Test

1. Set `OPENAI_API_KEY` in terminal
2. Start backend
3. Load sample data
4. POST `/api/reconcile/ai-triage`
5. Check response includes `llm_adjudicated_count`
6. GET `/api/reconcile/cases` and confirm "AI-Assisted Suggested Match" cases show LLM-generated reasons

---

## Files Changed

| File | Change |
|---|---|
| `backend/requirements.txt` | Add `openai>=1.30` |
| `backend/app/ai_triage.py` | Add `run_tier2c()` function |
| `backend/app/main.py` | Update import and `run_ai_triage()` to call `run_tier2c()` |

---

## Notes

- `temperature=0` ensures deterministic/reproducible LLM output
- `max_tokens=300` caps cost per call — the JSON response is always compact
- Graceful degradation: if `OPENAI_API_KEY` is missing, Tier 2b results are still returned; Tier 2c is silently skipped
- Cost estimate: ~$0.04 for 200 maybe-zone records (10,000 PSR/day scenario)
