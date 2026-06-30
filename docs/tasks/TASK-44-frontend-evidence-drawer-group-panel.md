# TASK-44 · Frontend — EvidenceDrawer: embedded group panel for N→1 and 1→N

**Type:** Frontend  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** TASK-40, TASK-41 (case payload now carries `psr_members` / `camt_members`)  
**Blocks:** TASK-45  
**Can run in parallel with:** TASK-42, TASK-43  
**Effort:** ~2–3 hours

---

## Background

The current EvidenceDrawer group panel:
1. Only renders for `match_type === "N_TO_1"` — P10 (`1_TO_N`) has no panel at all
2. Requires a second API call (`api.groupCases(group_id)`) to fetch sibling cases
3. Shows `internal_amount` for every row, which is wrong for the old ANCHOR row (shows group sum, not PSR amount)

After TASK-40 and TASK-41, the group members are embedded directly in the case payload as
`psr_members` (P6) and `camt_members` (P10). No extra API call is needed.

This task rewrites the group panel to:
- Render from embedded data (zero extra fetch)
- Support both `N_TO_1` (P6) and `1_TO_N` (P10)
- Show correct per-member amounts in both cases

---

## Acceptance Criteria

- [ ] P6 (`N_TO_1`) group panel renders a table with one row per entry in `case.psr_members`
  - Columns: PSR ID, Amount, Reference, Date
  - Each row shows the correct individual PSR amount (`member.amount`), not the group sum
- [ ] P10 (`1_TO_N`) split panel renders a table with one row per entry in `case.camt_members`
  - Columns: CAMT ID, Amount, Date
  - Each row shows the correct individual CAMT amount (`member.amount`)
- [ ] Panel header reads `"Group settlement — N PSRs → 1 bank entry"` for P6
- [ ] Panel header reads `"Split settlement — 1 PSR → N bank entries"` for P10
- [ ] The `siblingCases` state variable and the `api.groupCases()` fetch are **removed**
- [ ] `group_cases` API client method can be removed from `api/client.js` (no other callers)
- [ ] No click-to-navigate on member rows (rows are display-only — there's no separate case to navigate to)
- [ ] Panel does not render if `psr_members` / `camt_members` is absent or empty
- [ ] `npm run build` produces no new errors or warnings

---

## Implementation

### 1 — Remove `siblingCases` state and API fetch from `EvidenceDrawer` in `App.jsx`

Delete:
```js
const [siblingCases, setSiblingCases] = useState([]);
```

Delete the fetch inside the `useEffect`:
```js
if (d.case.group_id) {
  api.groupCases(d.case.group_id).then(res => setSiblingCases(res.items || [])).catch(() => setSiblingCases([]));
}
```

Delete the reset on drawer close:
```js
setSiblingCases([]);
```

### 2 — Replace the group panel render block in `App.jsx`

Find the existing panel (around line 919):
```jsx
{item.match_type === "N_TO_1" && siblingCases.length > 0 && (
  <div className="group-panel">
    ...
  </div>
)}
```

Replace with:
```jsx
{item.match_type === "N_TO_1" && item.psr_members?.length > 0 && (
  <div className="group-panel">
    <h4>Group settlement — {item.psr_members.length} PSR{item.psr_members.length !== 1 ? 's' : ''} → 1 bank entry</h4>
    <table className="group-sibling-table">
      <thead>
        <tr><th>PSR ID</th><th>Amount</th><th>Reference</th><th>Date</th></tr>
      </thead>
      <tbody>
        {item.psr_members.map(m => (
          <tr key={m.psr_id}>
            <td>{m.psr_id}</td>
            <td>{Number(m.amount).toFixed(2)}</td>
            <td>{m.reference || '—'}</td>
            <td>{m.date || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)}
{item.match_type === "1_TO_N" && item.camt_members?.length > 0 && (
  <div className="group-panel">
    <h4>Split settlement — 1 PSR → {item.camt_members.length} bank entr{item.camt_members.length !== 1 ? 'ies' : 'y'}</h4>
    <table className="group-sibling-table">
      <thead>
        <tr><th>CAMT ID</th><th>Amount</th><th>Date</th></tr>
      </thead>
      <tbody>
        {item.camt_members.map(m => (
          <tr key={m.ntry_id}>
            <td>{m.camt_id}</td>
            <td>{Number(m.amount).toFixed(2)}</td>
            <td>{m.date || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)}
```

### 3 — Remove `groupCases` from `frontend/src/api/client.js`

Delete the `groupCases` function. Verify no other component calls it before removing.

### 4 — CSS: no changes needed

`.group-panel`, `.group-sibling-table`, `.sibling-row` CSS classes already exist in `App.css`.
The `.sibling-row` hover/click style can be removed since rows are no longer navigable, but
it is harmless to leave in place.
