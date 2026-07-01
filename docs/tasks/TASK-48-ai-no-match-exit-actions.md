# TASK-48 · Frontend + Backend — No Match exit actions

**Type:** Full-stack (frontend-heavy, backend trivial)  
**Branch:** `feat/ai-candidate-picker`  
**Depends on:** TASK-47 (candidates panel should already exist; exit actions complement it)  
**Blocks:** —  
**Effort:** ~2–3 hours

---

## Background

`"AI Confirmed — No Match"` cases are currently dead ends. The status tells the analyst
"AI looked and found nothing" but offers no path forward. The analyst must either:
- Leave the case untouched (it sits in the queue forever)
- Go fully manual and type a freeform note

This task adds three **targeted exit actions** as quick-action buttons that appear specifically
for `NO_MATCH` cases, turning a dead end into a workflow step.

These actions reuse the existing `PATCH /api/reconcile/cases/{id}/resolve` endpoint — they
just set a specific `reason_code`. No new endpoint or schema change is needed.

---

## Acceptance Criteria

- [ ] Three exit action buttons appear in EvidenceDrawer **only** when
      `item.reconciliation_status === "AI Confirmed — No Match"`:
  - **"Post to Suspense Ledger"** — resolves with `reason_code: "SUSPENSE_LEDGER"`
  - **"Snooze — revisit next cycle"** — resolves with `reason_code: "SNOOZED_NEXT_CYCLE"`
  - **"Flag for Manual Investigation"** — resolves with `reason_code: "MANUAL_INVESTIGATION"`
- [ ] Each button click resolves the case immediately (calls the resolve endpoint inline,
      no modal required) with a pre-set `reason_code` and auto-generated `resolution_note`
- [ ] After resolution, the drawer closes and the results table refreshes (same pattern as
      the existing "Confirm match" button)
- [ ] The three buttons are visually distinct from the primary AI confirm/reject buttons —
      use a secondary/outlined button style
- [ ] Backend stores the `reason_code` as-is (no validation needed — it's a free TEXT column)

---

## Files to Change

| File | Change |
|---|---|
| `frontend/src/App.jsx` | New exit action button group in `EvidenceDrawer` |
| `backend/app/main.py` | No change required — reason_code is already stored verbatim |

---

## Implementation

### Where to add in `EvidenceDrawer`

Add after the AI candidates panel (TASK-47) and before the existing suggested-actions panel.
Gate on `reconciliation_status === "AI Confirmed — No Match"`:

```jsx
{item.reconciliation_status === 'AI Confirmed — No Match' && (
  <div className="no-match-exits">
    <p className="no-match-exits-label">
      AI found no suitable match. Choose how to handle this case:
    </p>
    <div className="no-match-exits-buttons">
      <button
        className="btn-exit"
        onClick={() => handleExitAction(item.result_id, 'SUSPENSE_LEDGER',
          'AI found no match. Posted to suspense ledger pending further investigation.')}
      >
        Post to Suspense Ledger
      </button>
      <button
        className="btn-exit"
        onClick={() => handleExitAction(item.result_id, 'SNOOZED_NEXT_CYCLE',
          'AI found no match. Snoozed — to be revisited in the next reconciliation cycle.')}
      >
        Snooze — revisit next cycle
      </button>
      <button
        className="btn-exit"
        onClick={() => handleExitAction(item.result_id, 'MANUAL_INVESTIGATION',
          'AI found no match. Flagged for manual investigation by reconciliation team.')}
      >
        Flag for Manual Investigation
      </button>
    </div>
  </div>
)}
```

### `handleExitAction` handler

Define inside `EvidenceDrawer` alongside the existing resolve handlers:

```jsx
const handleExitAction = async (caseId, reasonCode, note) => {
  try {
    await api.resolveCase(caseId, {
      resolution_type: 'manual_override',
      reason_code: reasonCode,
      resolution_note: note,
    });
    onClose();
    onRefresh();
  } catch (err) {
    // surface via existing error toast
  }
};
```

---

## CSS to Add in `App.css`

```css
.no-match-exits { margin: 14px 0; padding: 12px 14px; background: #fafafa; border: 1px solid #e2e8f0; border-radius: 8px; }
.no-match-exits-label { font-size: 0.8rem; color: #64748b; margin: 0 0 10px; }
.no-match-exits-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.btn-exit { font-size: 0.8rem; padding: 5px 12px; background: white; border: 1px solid #cbd5e1; border-radius: 6px; color: #475569; cursor: pointer; }
.btn-exit:hover { border-color: #94a3b8; background: #f8fafc; }
```

---

## Verification

1. Run AI triage — ensure at least one `"AI Confirmed — No Match"` case exists
2. Open that case in EvidenceDrawer
3. Verify three exit-action buttons appear
4. Click "Post to Suspense Ledger" — case resolves, drawer closes, table refreshes
5. Confirm the case in the DB has `reason_code = 'SUSPENSE_LEDGER'` and
   `reconciliation_status = 'Resolved Manually'`
6. Verify no exit buttons appear on a standard `AI-Assisted Suggested Match` case
