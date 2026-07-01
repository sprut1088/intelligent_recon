# TASK-46 · Backend — Enrich `candidates_reviewed` stored in `feature_snapshot_json`

**Type:** Backend  
**Branch:** `feat/ai-candidate-picker`  
**Depends on:** TASK-04 (Tier 2c LLM adjudication must exist)  
**Blocks:** TASK-47  
**Effort:** ~1 hour

---

## Background

After Tier 2c runs, each AI case stores a `feature_snapshot_json` blob that includes a
`candidates_reviewed` list — the CAMT entries the LLM considered when making its decision.
The frontend (TASK-47) will read this list to display selectable alternatives, but two gaps
exist today:

1. **Only top 3 stored** — `result["_candidates"] = top_candidates[:3]` in `_process_psr()`.
   We should store all 5 so the analyst sees the full picture.
2. **Missing fields** — `candidates_reviewed` entries currently carry `camt_id, counterparty,
   amount, currency, date, remittance, domain_score` but are missing `pmt_ref` and `invoice`.
   These are needed so the frontend "Use this" pre-fill can populate the Resolve modal correctly.

No DB schema change is required — `feature_snapshot_json` is already a TEXT column.

---

## Acceptance Criteria

- [ ] `_process_psr()` stores all 5 candidates: `result["_candidates"] = top_candidates[:5]`
- [ ] Each entry in `candidates_reviewed` includes two new fields:
  - `"pmt_ref"`: from `c.get("camt_pmt_ref") or ""`
  - `"invoice"`: from `c.get("camt_invoice") or ""`
- [ ] All three Tier 2c decision types (`CONFIRM_AI_MATCH`, `ROUTE_TO_ANALYST`, `NO_MATCH`)
      produce a `candidates_reviewed` list with up to 5 enriched entries
- [ ] Existing tests pass — no functional behaviour changed, only stored metadata extended

---

## Files to Change

| File | Change |
|---|---|
| `backend/app/ai_triage.py` | Two small edits (see below) |

---

## Implementation

### Edit 1 — `_process_psr()` — line where `_candidates` is attached to result

**Find:**
```python
            result["_candidates"] = top_candidates[:3]
```

**Replace with:**
```python
            result["_candidates"] = top_candidates[:5]
```

### Edit 2 — `candidates_reviewed` list comprehension in `run_tier2c()`

**Find:**
```python
        candidates_reviewed = [
            {
                "camt_id": c.get("camt_id"),
                "counterparty": c.get("camt_counterparty") or "",
                "amount": c.get("camt_amount"),
                "currency": c.get("camt_currency") or "",
                "date": c.get("camt_booking_date") or "",
                "remittance": c.get("camt_remittance") or "",
                "domain_score": c.get("candidate_score"),
            }
            for c in result.get("_candidates", [])
        ]
```

**Replace with:**
```python
        candidates_reviewed = [
            {
                "camt_id": c.get("camt_id"),
                "counterparty": c.get("camt_counterparty") or "",
                "amount": c.get("camt_amount"),
                "currency": c.get("camt_currency") or "",
                "date": c.get("camt_booking_date") or "",
                "pmt_ref": c.get("camt_pmt_ref") or "",
                "invoice": c.get("camt_invoice") or "",
                "remittance": c.get("camt_remittance") or "",
                "domain_score": c.get("candidate_score"),
            }
            for c in result.get("_candidates", [])
        ]
```

---

## Verification

Run the AI triage endpoint with a live DB and inspect the stored `feature_snapshot_json`
for one AI case:

```sql
SELECT json_extract(feature_snapshot_json, '$.candidates_reviewed') 
FROM recon_cases 
WHERE case_id LIKE 'AI%' 
LIMIT 3;
```

Each row should show up to 5 objects, each containing `pmt_ref` and `invoice` keys.
