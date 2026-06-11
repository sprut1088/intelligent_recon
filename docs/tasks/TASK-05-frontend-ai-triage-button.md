# TASK-05 · Frontend — Wire AI triage API client and add "Run AI triage" button

**Type:** Frontend  
**Branch:** `feature/residual-match-ai`  
**Depends on:** TASK-03 (`POST /api/reconcile/ai-triage` endpoint must exist)  
**Blocks:** TASK-07  
**Can run in parallel with:** TASK-06  
**Effort:** ~2–3 hours

---

## Background

The backend AI triage endpoint exists after TASK-03. This task wires it to the frontend:
1. Add the API client call in `client.js`
2. Add a "Run AI triage" button in the Results Workbench header toolbar
3. After the button is clicked, refresh the results table to show new AI-suggested cases

The pattern to follow is identical to how "Run learner" works in the Learning Lab tab.

---

## Acceptance Criteria

- [ ] `api.aiTriage()` function added to `frontend/src/api/client.js`
- [ ] "Run AI triage" button appears in Results Workbench toolbar, to the right of the "Apply" search button
- [ ] Button is disabled while a request is in flight (`loading` state)
- [ ] After successful call, results are refreshed automatically (calls `refreshResults()`)
- [ ] Toast/status message appears on success: e.g. `"AI triage complete — X new suggestions added"`
- [ ] If the backend returns an error (e.g. model not loaded), the error is surfaced via the existing error toast mechanism

---

## Implementation

### Step 1 — Add to `frontend/src/api/client.js`

Find the existing API object and add:
```js
aiTriage: () => request('/api/reconcile/ai-triage', { method: 'POST' }),
```

Place it near the other reconciliation calls (`runBatch`, etc.).

### Step 2 — Add button to `ResultsWorkbench` component in `frontend/src/App.jsx`

Find the `ResultsWorkbench` function signature:
```jsx
function ResultsWorkbench({ results, selected, setSelected, refreshResults }) {
```

Update signature to accept `onAiTriage` and `loading`:
```jsx
function ResultsWorkbench({ results, selected, setSelected, refreshResults, onAiTriage, loading }) {
```

In the toolbar `div`, add the new button after the existing "Apply" button:
```jsx
<button
  className="btn primary"
  disabled={loading}
  onClick={onAiTriage}
>
  Run AI triage
</button>
```

### Step 3 — Add handler in the main `App` component

Find the section where other async handlers are defined (near `runSelectedBatch`, `validateSelectedBatch`, etc.) and add:

```jsx
const runAiTriage = async () => {
  await safe(async () => {
    const result = await api.aiTriage();
    await refreshResults({ search: '', exceptionOnly: false });
    return result;
  }, `AI triage complete — ${result?.clear_count ?? 0} suggestions added`);
};
```

Note: the `safe()` wrapper already handles loading state and error toasts — use it consistently.

### Step 4 — Pass handler down to `ResultsWorkbench`

Find the line in the render switch that returns `<ResultsWorkbench .../>` and add the new props:
```jsx
if (active === 'results') return <ResultsWorkbench
  results={results}
  selected={selected}
  setSelected={setSelected}
  refreshResults={refreshResults}
  onAiTriage={runAiTriage}
  loading={loading}
/>;
```

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/api/client.js` | Add `aiTriage` function |
| `frontend/src/App.jsx` | Update `ResultsWorkbench` signature; add "Run AI triage" button; add `runAiTriage` handler; pass props |

---

## Notes

- The button label "Run AI triage" mirrors the "Run learner" button in the Learning Lab — consistent UX language
- Do not add a confirmation dialog — the operation is reversible (a deterministic rerun wipes AI cases)
- The button should visually sit separate from the search/filter controls — consider a vertical divider `|` or gap if the toolbar gets crowded
