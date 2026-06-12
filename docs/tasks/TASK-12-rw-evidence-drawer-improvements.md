# TASK-12 · Results Workbench — Evidence Drawer Improvements

**Type:** Frontend  
**Branch:** `fix/ui-result-workbench`  
**Depends on:** —  
**Blocks:** —  
**Can run in parallel with:** TASK-08, TASK-09, TASK-10, TASK-11, TASK-13  
**Effort:** ~2–3 hours

---

## Background

The evidence drawer has three independent usability gaps:

1. **No backdrop** — the drawer slides in but the table behind is still fully interactive.
   Clicking any row while the drawer is open replaces the selection silently.
2. **Generic resolve button** — the "Resolve and capture learning" button shows for all
   exception cases regardless of AI status. A `TIER2C_LLM` suggested match should offer a
   "Confirm match" primary action; the generic resolve should be secondary.
3. **Confidence shown as raw decimal** — suggestion confidence displays as `0.6655` instead of
   `66.6%`. Minor but looks unpolished in a client demo.
4. **No prev/next navigation** — once the drawer is open the analyst must close it and click
   another row to move between cases. Arrow navigation would significantly speed up triage.

---

## Observations covered

| # | Description |
|---|---|
| 10 | Drawer has no backdrop — table behind remains clickable and scrollable |
| 11 | "Resolve and capture learning" shown for all exception cases regardless of AI action |
| 12 | Suggestion confidence shows as raw decimal instead of percentage |
| 13 | No prev/next case navigation inside the drawer |

---

## Acceptance Criteria

- [ ] A semi-transparent backdrop renders behind the drawer when it is open; clicking the backdrop closes the drawer
- [ ] `TIER2C_LLM` / `CONFIRM_AI_MATCH` cases show a **"Confirm AI match"** primary button; "Resolve and capture learning" is shown as a secondary ghost button below it
- [ ] All other exception cases show only "Resolve and capture learning" as before
- [ ] Suggestion confidence values are formatted as `XX.X%` (multiply by 100, one decimal place)
- [ ] Prev **←** and Next **→** arrow buttons appear at the top of the drawer
- [ ] Prev/Next navigate through the current filtered `results.items` array by index
- [ ] Prev is disabled when the first row is selected; Next is disabled when the last row is selected

---

## Implementation Notes

### Backdrop
```jsx
{selected && <div className="drawer-backdrop" onClick={onClose} />}
```
```css
.drawer-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.25); z-index: 99; }
.drawer { z-index: 100; /* ensure above backdrop */ }
```

### Context-aware action buttons
```jsx
const aiSuggestion = suggestions.find(s => s.action === 'CONFIRM_AI_MATCH');
{aiSuggestion && selected.exception_flag === 'Y' && (
  <button className="btn primary full" onClick={() => onResolve(selected, 'CONFIRM_AI_MATCH')}>
    Confirm AI match
  </button>
)}
{selected.exception_flag === 'Y' && (
  <button className={`btn ${aiSuggestion ? 'ghost' : 'primary'} full`} onClick={() => onResolve(selected)}>
    Resolve and capture learning
  </button>
)}
```

### Confidence formatting
```jsx
<p>{s.reason || (s.confidence != null ? `${(s.confidence * 100).toFixed(1)}%` : '')}</p>
```

### Prev / Next navigation
Pass `rows` and `selectedIndex` down to `EvidenceDrawer`:
```jsx
<EvidenceDrawer
  selected={selected}
  selectedIndex={rows.findIndex(r => r.result_id === selected?.result_id)}
  total={rows.length}
  onPrev={() => setSelected(rows[selectedIndex - 1])}
  onNext={() => setSelected(rows[selectedIndex + 1])}
  ...
/>
```
```jsx
<div className="drawer-nav">
  <button disabled={selectedIndex <= 0} onClick={onPrev}>← Prev</button>
  <span>{selectedIndex + 1} / {total}</span>
  <button disabled={selectedIndex >= total - 1} onClick={onNext}>Next →</button>
</div>
```

---

## Files to change

- `frontend/src/App.jsx` — `EvidenceDrawer`, `ResultsWorkbench`
- `frontend/src/App.css` or `frontend/src/styles.css` — backdrop, drawer z-index, nav styles
