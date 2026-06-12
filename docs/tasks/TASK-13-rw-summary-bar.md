# TASK-13 · Results Workbench — Toolbar & Table Summary Bar

**Type:** Frontend  
**Branch:** `fix/ui-result-workbench`  
**Depends on:** TASK-09 (pagination state)  
**Blocks:** —  
**Can run in parallel with:** TASK-08, TASK-10, TASK-11, TASK-12  
**Effort:** ~1 hour

---

## Background

The workbench header gives no summary of what is currently loaded. After running AI triage or
reconciliation the analyst has no at-a-glance count of matched vs exception vs AI-suggested
records. A thin summary bar between the toolbar and the table would give instant orientation.

---

## Observations covered

This is a net-new addition (not one of the 13 bugs) but directly supports the usability of
the workbench and is a natural companion to TASK-09 pagination.

---

## Acceptance Criteria

- [ ] A summary bar appears between the toolbar and the table with these counts (derived from `results.items`):
  - **Total** (from `results.total`)
  - **Matched** — status contains "Matched" or "Auto-Close"
  - **AI Suggested** — status is `"AI-Assisted Suggested Match"`
  - **Exceptions** — `exception_flag === 'Y'` and not AI-suggested
  - **In-Transit** — status contains "In-Transit" or "Uncleared"
- [ ] Clicking a count chip applies that filter (equivalent to selecting that status in the dropdown from TASK-08)
- [ ] Active chip is highlighted
- [ ] The bar updates reactively as `results.items` changes (after AI triage, after search)

---

## Implementation Notes

### Summary bar component
```jsx
function SummaryBar({ items = [], total = 0, onFilter }) {
  const count = (predicate) => items.filter(predicate).length;
  const chips = [
    { label: 'Total', value: total, filter: '' },
    { label: 'Matched', value: count(r => r.reconciliation_status?.includes('Matched')), filter: 'Matched & Settled (Auto-Close)' },
    { label: 'AI Suggested', value: count(r => r.reconciliation_status === 'AI-Assisted Suggested Match'), filter: 'AI-Assisted Suggested Match' },
    { label: 'Exceptions', value: count(r => r.exception_flag === 'Y' && !r.reconciliation_status?.startsWith('AI')), filter: 'exceptions' },
    { label: 'In-Transit', value: count(r => r.reconciliation_status?.includes('In-Transit')), filter: 'Uncleared / In-Transit Payment' },
  ];
  return (
    <div className="summary-bar">
      {chips.map(c => (
        <button key={c.label} className="chip" onClick={() => onFilter(c.filter)}>
          <strong>{c.value}</strong><span>{c.label}</span>
        </button>
      ))}
    </div>
  );
}
```

Place between toolbar and `<ResultTable>` in `ResultsWorkbench`.

### CSS
```css
.summary-bar { display: flex; gap: 0.5rem; padding: 0.5rem 0; }
.chip { background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.75rem; cursor: pointer; display: flex; flex-direction: column; align-items: center; }
.chip strong { font-size: 1.1rem; }
.chip span   { font-size: 0.7rem; color: var(--text-muted); }
.chip.active { border-color: var(--accent); background: var(--accent-light); }
```

---

## Files to change

- `frontend/src/App.jsx` — new `SummaryBar` component, `ResultsWorkbench`
- `frontend/src/App.css` or `frontend/src/styles.css` — chip styles
