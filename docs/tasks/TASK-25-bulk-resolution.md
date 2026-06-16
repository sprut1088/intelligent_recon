# TASK-25 · Evidence Drawer — Stage 6: Bulk Resolution

**Type:** Full-stack  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-19 (override reason capture — bulk actions must carry learning signal tags), TASK-23 (filter navigation — bulk scope is the filtered set)  
**Blocks:** —  
**Can run in parallel with:** TASK-24  
**Effort:** ~5–6 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 6, item 16

---

## Background

After per-item UX (Stages 1–4) and navigation efficiency (Stage 5) are mature, the final scale feature is bulk resolution: select all items matching the current filter and apply the same resolution + shared reason in one operation.

This must not be built earlier. Bulk actions amplify whatever is in the per-item flow — including any bugs in the learning signal. Building it before TASK-19 would inject uncategorised noise into the model at scale.

---

## Acceptance Criteria

### Frontend

- [ ] A "Select all in filter" checkbox appears in the `ResultsWorkbench` toolbar when a filter is active (from TASK-23's filter state)
- [ ] Selecting it highlights all filtered items in the results table with a selection state
- [ ] A "Bulk resolve" action bar appears at the bottom of the screen when ≥2 items are selected:
  - Shows count: `"14 items selected"`
  - Dropdown: **Resolution** — same options as Suggested Actions (Accept AI Match / Mark as No Match / Escalate for Review)
  - Dropdown: **Reason** — same options as TASK-19's override reason dropdown (required when resolution is Override)
  - **"Apply to all selected"** button
  - **"Clear selection"** link
- [ ] Confirmation step required before submit: `"Apply 'Mark as No Match' to 14 items? This cannot be undone."` — confirm/cancel dialog
- [ ] After confirmation, calls backend bulk endpoint; shows progress (spinner or count of processed items)
- [ ] Results refresh after completion; selection is cleared

### Backend

- [ ] New endpoint: `POST /api/reconcile/resolve/bulk`
- [ ] Request body: `{ case_ids: [int], status: str, resolution_type: str, override_reason?: str, override_note?: str }`
- [ ] Validates that `case_ids` are all owned by the current session's loaded data (no IDOR — validate each ID exists in `recon_cases` before updating)
- [ ] Applies the same `UPDATE` logic as the single-item resolve endpoint, in a single transaction
- [ ] Returns: `{ updated: int, skipped: int, errors: [] }`
- [ ] Maximum batch size: 500 items per request (reject with 400 if exceeded)

---

## Implementation Notes

### Security — IDOR prevention

```python
@app.post("/api/reconcile/resolve/bulk")
async def bulk_resolve(req: BulkResolveRequest):
    if len(req.case_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 items per bulk operation.")
    with get_conn() as conn:
        # Validate all IDs exist before updating any
        placeholders = ",".join("?" * len(req.case_ids))
        existing = conn.execute(
            f"SELECT id FROM recon_cases WHERE id IN ({placeholders})",
            req.case_ids
        ).fetchall()
        valid_ids = {r["id"] for r in existing}
        invalid = set(req.case_ids) - valid_ids
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unknown case IDs: {sorted(invalid)}")
        # Single transaction update
        conn.executemany(
            """UPDATE recon_cases SET reconciliation_status=?, resolution_type=?,
               override_reason=?, override_note=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            [(req.status, req.resolution_type, req.override_reason, req.override_note, i)
             for i in valid_ids]
        )
        conn.commit()
    return {"updated": len(valid_ids), "skipped": 0, "errors": []}
```

### Frontend confirmation pattern

Use the existing pattern for destructive actions in the app (check how batch delete or similar is handled). If no confirmation pattern exists, add a simple inline confirm step (not a `window.confirm()` — use a state-driven confirm bar).
