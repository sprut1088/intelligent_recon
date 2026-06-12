# TASK-10 · Results Workbench — Column Sorting & Variance Colour Fix

**Type:** Frontend  
**Branch:** `fix/ui-result-workbench`  
**Depends on:** —  
**Blocks:** —  
**Can run in parallel with:** TASK-08, TASK-09, TASK-11, TASK-12, TASK-13  
**Effort:** ~1–2 hours

---

## Background

Two independent table display issues:

1. No column sorting — clicking a header does nothing. Confidence, Variance, and Status are
   the most useful sort axes for an analyst triaging exceptions.
2. Variance colour logic is wrong — `Number(r.variance) === 0 ? 'positive' : 'negative'`
   marks every non-zero variance red, including tiny acceptable amounts (e.g. €0.01 rounding
   differences). Should only show red for variances above the minor tolerance threshold.

---

## Observations covered

| # | Description |
|---|---|
| 6 | No column sorting — headers are not clickable |
| 7 | Variance cell is red for any non-zero value, including trivially small ones |

---

## Acceptance Criteria

- [ ] Clicking a column header sorts the table by that column (ascending first, second click descending)
- [ ] Sortable columns: **Confidence**, **Variance**, **Status**, **Rule**
- [ ] Active sort column shows a ▲ / ▼ indicator
- [ ] Sorting is client-side (operates on `results.items` in memory — no new API call needed)
- [ ] Variance cell colour logic:
  - `€0.00` exactly → green (`positive`)
  - Non-zero but within `MINOR_VARIANCE_TOLERANCE` (€50) → amber (`warning`)
  - Above threshold → red (`negative`)
  - `null` / missing → neutral, displays `-`

---

## Implementation Notes

### Sort state
```jsx
const [sortCol, setSortCol] = useState(null);   // column key string
const [sortDir, setSortDir] = useState('asc');

const sorted = useMemo(() => {
  if (!sortCol) return rows;
  return [...rows].sort((a, b) => {
    const av = a[sortCol] ?? '';
    const bv = b[sortCol] ?? '';
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });
}, [rows, sortCol, sortDir]);
```

### Sortable header
```jsx
function SortTh({ col, label, sortCol, sortDir, onSort }) {
  const active = sortCol === col;
  return (
    <th onClick={() => onSort(col)} style={{ cursor: 'pointer' }}>
      {label} {active ? (sortDir === 'asc' ? '▲' : '▼') : ''}
    </th>
  );
}
```

### Variance colour fix
```jsx
const MINOR_TOLERANCE = 50; // ideally read from a config endpoint
const varianceTone = (v) => {
  if (v === null || v === undefined) return '';
  if (v === 0) return 'positive';
  if (Math.abs(v) <= MINOR_TOLERANCE) return 'warning';
  return 'negative';
};
```
```jsx
<td className={varianceTone(r.variance)}>{r.variance != null ? money(r.variance) : '-'}</td>
```

---

## Files to change

- `frontend/src/App.jsx` — `ResultTable` component
