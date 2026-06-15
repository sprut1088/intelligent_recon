# TASK-22 · Evidence Drawer — Stage 4c: Direct Links to Source Records

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-15 (raw PSR/CAMT fields must be available in the API response)  
**Blocks:** —  
**Can run in parallel with:** TASK-19, TASK-20, TASK-21  
**Effort:** ~1–2 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 4, item 13

---

## Background

Invoice numbers, counterparty names, and payment references in the drawer are currently plain text. Making them clickable — linking to the raw CAMT or PSR transaction record — lets power users quickly cross-reference source data without leaving the workflow.

This task assumes TASK-15 has confirmed or added a detail endpoint (`GET /api/reconcile/results/{case_id}` or equivalent) that surfaces the raw record IDs.

---

## Acceptance Criteria

- [ ] In the drawer header and field diff, PSR `psr_id` is rendered as a link: clicking opens the raw PSR record (detail endpoint or anchor link to the transactions table if a full drill-down view does not yet exist)
- [ ] In the field diff, CAMT `camt_id` is rendered as a link similarly
- [ ] If no detail endpoint exists yet (decided in TASK-15), the links are formatted as `#psr-{id}` fragment anchors — stub behaviour that does not break the UI
- [ ] Invoice field values (`psr_invoice`, `camt_invoice`) in the field diff are rendered as plain text (not links) — invoice drill-down is out of scope for this task
- [ ] Links open in the same tab (no `target="_blank"` — the drawer is already a side panel within the app)
- [ ] Link styling is consistent with existing link colours in the app

---

## Implementation Notes

### Link rendering

In `FieldDiff` (from TASK-16), the ID row becomes:

```jsx
{ label: 'ID', psr: <a href={`#psr-${item.psr_id}`}>{item.psr_id}</a>, camt: <a href={`#camt-${item.camt_id}`}>{item.camt_id}</a> }
```

Note: `FieldDiff` renders values as strings — update it to accept `ReactNode` values, or add a separate IDs row outside the diff table.

### Future upgrade path

When a dedicated PSR/CAMT transaction detail view is added to the app, update these `href` values from fragment anchors to real routes. No change needed in this task.
