# TASK-20 · Evidence Drawer — Stage 4a: Similar Resolved Cases Panel

**Type:** Full-stack  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-19 (learning signal tagging must exist — similar cases are only meaningful once override vs. agree is distinguished)  
**Blocks:** —  
**Can run in parallel with:** TASK-21, TASK-22  
**Effort:** ~3–4 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 4, item 11

---

## Background

When a user reviews an ambiguous case, knowing that "3 similar counterparty mismatches in this batch were all resolved as No Match" dramatically reduces cognitive load on repetitive decisions. This contextual signal builds user confidence without requiring them to navigate away from the current item.

Depends on TASK-19 because the count is only useful if similar cases carry clean learning signals (not mixed with uncategorised overrides).

---

## Acceptance Criteria

### Backend

- [ ] New endpoint: `GET /api/reconcile/similar/{case_id}?limit=5`
- [ ] Returns up to 5 cases where:
  - `rule_applied` matches the current case's rule, **or**
  - `camt_counterparty` or `psr_counterparty` overlap (fuzzy, same first token is sufficient for V1)
  - Case is already resolved (`reconciliation_status` ∈ `{'Matched', 'Uncleared / In-Transit Payment', 'Exception'}`)
  - Case is **not** the current case
- [ ] Response shape per item: `{ id, psr_id, rule_applied, reconciliation_status, resolution_type, resolved_at }`
- [ ] If no similar cases exist, return `{ items: [], count: 0 }` (not a 404)

### Frontend

- [ ] A collapsible "Similar resolved cases" section appears in the drawer below the field diff
- [ ] Shows count summary: e.g., `"3 similar cases — 2 No Match, 1 Matched"`
- [ ] Collapsed by default; user clicks to expand
- [ ] Expanded view lists up to 5 cases with: rule label (from `RULE_LABELS`), outcome, resolution type (agree/override)
- [ ] Section is hidden when count is 0
- [ ] Fetches lazily on drawer open (does not block initial render)

---

## Implementation Notes

### Backend query (V1 — simple rule match)

```python
@app.get("/api/reconcile/similar/{case_id}")
async def get_similar_cases(case_id: int, limit: int = 5):
    with get_conn() as conn:
        current = conn.execute(
            "SELECT rule_applied, psr_counterparty FROM recon_cases WHERE id = ?", (case_id,)
        ).fetchone()
        if not current:
            raise HTTPException(status_code=404)
        rows = conn.execute(
            """SELECT id, psr_id, rule_applied, reconciliation_status, resolution_type, updated_at
               FROM recon_cases
               WHERE id != ?
                 AND rule_applied = ?
                 AND reconciliation_status NOT IN ('Uncleared / In-Transit Payment',
                                                   'AI - Analyst Adjudication Required')
               ORDER BY updated_at DESC
               LIMIT ?""",
            (case_id, current["rule_applied"], limit)
        ).fetchall()
    return {"items": rows_to_dicts(rows), "count": len(rows)}
```

### Frontend fetch pattern

```jsx
const [similarCases, setSimilarCases] = useState(null);  // null = not yet loaded

useEffect(() => {
  if (!item) return;
  setSimilarCases(null);
  api.similarCases(item.id).then(setSimilarCases).catch(() => setSimilarCases({ items: [], count: 0 }));
}, [item?.id]);
```
