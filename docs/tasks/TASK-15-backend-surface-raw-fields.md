# TASK-15 · Backend — Surface Raw PSR & CAMT Fields in Triage API Response

**Type:** Backend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** —  
**Blocks:** TASK-16, TASK-22  
**Can run in parallel with:** TASK-14  
**Effort:** ~1–2 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 2, Note

---

## Background

The evidence drawer's Stage 2 field diff (TASK-16) needs to show the raw PSR and CAMT field values side by side. Before starting TASK-16, verify whether the existing `GET /api/reconcile/results` response already includes these fields — and if not, extend it.

The investigation checklist is the actual deliverable. If fields are present, this task closes immediately. If not, this task adds them.

---

## Acceptance Criteria

- [ ] **Audit**: For a resolved AI triage case, confirm the API response for `GET /api/reconcile/results` (or the detail endpoint) includes:
  - PSR fields: `psr_reference`, `psr_invoice`, `psr_counterparty`, `psr_amount`, `psr_currency`, `psr_execution_date`, `psr_direction`
  - CAMT fields: `camt_remittance`, `camt_counterparty`, `camt_amount`, `camt_currency`, `camt_booking_date`, `camt_direction`, `camt_pmt_ref`, `camt_invoice`
- [ ] If fields are **already present**: document which endpoint surfaces them and mark this task complete.
- [ ] If fields are **missing from the results list endpoint** but present in the DB schema: extend `GET /api/reconcile/results` (or add a `GET /api/reconcile/results/{case_id}` detail endpoint) to include them.
- [ ] The `feature_snapshot_json` field stored by `run_tier2b()` already captures these fields in the candidate dict — confirm they are persisted and re-surfaced correctly.
- [ ] No breaking change to the existing response shape (add fields, don't rename or remove).

---

## Implementation Notes

### Where to check first

`backend/app/main.py` — the `GET /api/reconcile/results` handler. Inspect which columns it selects from `recon_cases`.

`backend/app/reconciliation.py` — the `recon_cases` insert to confirm PSR/CAMT raw fields are stored or join-able.

### If a detail endpoint is needed

```python
@app.get("/api/reconcile/results/{case_id}")
async def get_recon_case(case_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rc.*, p.*, c.* FROM recon_cases rc "
            "LEFT JOIN psr_transactions p ON rc.psr_id = p.id "
            "LEFT JOIN camt_transactions c ON rc.camt_id = c.camt_id "
            "WHERE rc.id = ?", (case_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    return dict(row)
```

### Security note

Do not expose internal database row IDs or any fields beyond the defined PSR/CAMT field list above. Select explicit columns rather than `SELECT *` in production.
