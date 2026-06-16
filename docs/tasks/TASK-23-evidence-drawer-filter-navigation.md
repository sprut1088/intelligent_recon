# TASK-23 · Evidence Drawer — Stage 5a: Filterable Navigation

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-14, TASK-16, TASK-17, TASK-18, TASK-19 (per-item experience must be solid before optimising navigation speed)  
**Blocks:** TASK-24, TASK-25  
**Can run in parallel with:** —  
**Effort:** ~3–4 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 5, item 14

---

## Background

The current Prev/Next navigation cycles through all results sequentially. Users handling large batches (50–500 items) have no way to prioritise: they cannot jump to low-confidence items first, skip already-resolved items, or work through a single rule type before moving on.

This task replaces the simple `1/N Prev Next` with a filter-aware navigation strip so users can scope their review queue before entering the drawer.

---

## Acceptance Criteria

- [ ] The drawer navigation bar shows a filter selector with options:
  - **All** (default — current behaviour)
  - **AI suggested** (filter to items with `rule_applied` starting with `TIER2`)
  - **Low confidence** (filter to items with `match_confidence < 60`)
  - **Exceptions only** (filter to `reconciliation_status = 'Exception'`)
  - **Unreviewed** (filter to items not yet resolved in this session — tracked client-side)
- [ ] When a filter is active, the `N/Total` counter reflects the filtered count (e.g., `"3/7 AI suggested"`)
- [ ] Prev/Next buttons navigate within the filtered set, not the full list
- [ ] The selected filter persists while the drawer is open; changing filter resets position to item 1 of the new set
- [ ] "Clear filter" control resets to All
- [ ] The filter selector is accessible (keyboard focusable, labelled)

---

## Implementation Notes

### State in `ResultsWorkbench` or lifted to `App`

```jsx
const [drawerFilter, setDrawerFilter] = useState('all');

const filteredItems = useMemo(() => {
  const items = results.items ?? [];
  switch (drawerFilter) {
    case 'ai':        return items.filter(r => r.rule_applied?.startsWith('TIER2'));
    case 'low':       return items.filter(r => r.match_confidence != null && r.match_confidence < 60);
    case 'exception': return items.filter(r => r.reconciliation_status === 'Exception');
    default:          return items;
  }
}, [results.items, drawerFilter]);
```

Pass `filteredItems` to `EvidenceDrawer` instead of the full `results.items`.

### Drawer nav bar

```jsx
<div className="drawer-nav">
  <button onClick={onPrev} disabled={drawerIdx === 0}>‹ Prev</button>
  <span>{drawerIdx + 1} / {filteredItems.length}
    {drawerFilter !== 'all' && <span className="filter-badge">{FILTER_LABELS[drawerFilter]}</span>}
  </span>
  <select value={drawerFilter} onChange={e => setDrawerFilter(e.target.value)} aria-label="Filter review queue">
    <option value="all">All</option>
    <option value="ai">AI suggested</option>
    <option value="low">Low confidence</option>
    <option value="exception">Exceptions</option>
  </select>
  <button onClick={onClose}>Close</button>
</div>
```
