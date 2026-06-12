# TASK-09 · Results Workbench — Record Count & Pagination

**Type:** Frontend  
**Branch:** `fix/ui-result-workbench`  
**Depends on:** —  
**Blocks:** —  
**Can run in parallel with:** TASK-08, TASK-10, TASK-11, TASK-12, TASK-13  
**Effort:** ~2–3 hours

---

## Background

The results table is hardcoded to fetch `limit: 150`. With 10,000 sample records loaded, the
user sees only the first 150 with no indication that more exist. There are no pagination
controls and no record count shown in the UI.

---

## Observations covered

| # | Description |
|---|---|
| 4 | No record count shown — user cannot tell how many records are loaded vs total |
| 5 | No pagination — hardcoded `limit: 150`, no way to navigate beyond first page |

---

## Acceptance Criteria

- [ ] A record count label appears above or below the table: e.g. **"Showing 1–100 of 941"**
- [ ] Prev / Next pagination buttons appear below the table
- [ ] Page size options: 50 / 100 / 250 (default 100)
- [ ] Current page is tracked in component state; changing the filter resets to page 1
- [ ] `api.results()` is called with correct `limit` and `offset` based on current page and page size
- [ ] Pagination controls are disabled when on first/last page respectively
- [ ] Total count displayed comes from `results.total` returned by the API

---

## Implementation Notes

### State additions to `ResultsWorkbench`
```jsx
const [page, setPage] = useState(0);
const [pageSize, setPageSize] = useState(100);
const totalPages = Math.ceil((results.total || 0) / pageSize);
```

### Updated `refreshResults` call signature
```js
api.results({ limit: pageSize, offset: page * pageSize, exceptionOnly, search, status })
```

### Count label
```jsx
<span className="record-count">
  Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, results.total || 0)} of {results.total || 0}
</span>
```

### Pagination controls (below table)
```jsx
<div className="pagination">
  <button disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Prev</button>
  <span>Page {page + 1} of {totalPages}</span>
  <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>Next →</button>
</div>
```

Changing `page` triggers a `useEffect` that calls `refreshResults`.

---

## Files to change

- `frontend/src/App.jsx` — `ResultsWorkbench`, `ResultTable` (count label + pagination)
- `frontend/src/api/client.js` — confirm `offset` is passed through correctly (it is, just hardcoded to 0)
