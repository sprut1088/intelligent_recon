# TASK-08 · Results Workbench — Search UX & Status Filter

**Type:** Frontend  
**Branch:** `fix/ui-result-workbench`  
**Depends on:** —  
**Blocks:** —  
**Can run in parallel with:** TASK-09, TASK-10, TASK-11, TASK-12, TASK-13  
**Effort:** ~1–2 hours

---

## Background

The current search bar requires the user to click "Apply" to trigger a filter. There is also no
way to filter by reconciliation status — the only options are free-text search and an
"Exceptions only" checkbox. Both gaps slow down analyst triage.

---

## Observations covered

| # | Description |
|---|---|
| 1 | Search fires only on "Apply" click — no Enter key support |
| 2 | "Exceptions only" toggle requires a separate "Apply" click to take effect |
| 3 | No status filter dropdown (Matched / In-Transit / AI-Assisted / etc.) |

---

## Acceptance Criteria

- [ ] Pressing **Enter** inside the search input triggers the same filter action as clicking "Apply"
- [ ] Toggling "Exceptions only" fires the filter immediately (no Apply click needed)
- [ ] A **Status** dropdown appears in the toolbar with options:
  - All statuses (default)
  - Matched & Settled (Auto-Close)
  - Uncleared / In-Transit Payment
  - AI-Assisted Suggested Match
  - AI - Analyst Adjudication Required
  - Post to Short or Over Ledger
  - Suggested Match - Analyst Review
- [ ] Status filter is passed to `refreshResults()` and forwarded to the API as a `status` query param
- [ ] All three filters (search text, exceptions-only, status) compose — applying two at once produces an AND result

---

## Implementation Notes

### Enter key on search input
```jsx
<input
  value={search}
  onChange={(e) => setSearch(e.target.value)}
  onKeyDown={(e) => e.key === 'Enter' && runSearch()}
  placeholder="Search PSR, CAMT, invoice, party"
/>
```

### Immediate toggle for Exceptions only
```jsx
onChange={(e) => {
  setExceptionOnly(e.target.checked);
  refreshResults({ search, exceptionOnly: e.target.checked, status: selectedStatus });
}}
```

### Status filter
Add a `selectedStatus` state string (default `''`). Pass it into `refreshResults` and on to
`api.results()`. The backend `GET /api/reconcile/cases` already accepts a `status` query param.

---

## Files to change

- `frontend/src/App.jsx` — `ResultsWorkbench` component and `runSearch` handler
- `frontend/src/api/client.js` — pass `status` param through `api.results()`
