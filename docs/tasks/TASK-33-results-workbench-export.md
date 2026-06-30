# TASK-33 · Results Workbench — Download Reconciliation Report

**Type:** Full-stack  
**Branch:** `feat/rw-export`  
**Depends on:** None (standalone)  
**Blocks:** Nothing  
**Effort:** ~2–3 hours

---

## Background

A generic CSV export already exists at `GET /api/workspace/export/reconciliation-results`
(see `workspace.py → export_reconciliation_results()`), but it has two problems:

1. **No filter support** — it dumps every row in `recon_cases` regardless of the analyst's
   current search, status filter, or exception-only toggle in the Results Workbench.
2. **Not wired to Results Workbench** — the "Export CSV" button exists on the Workspace and
   Dashboards tabs only; there is no download affordance in `ResultsWorkbench`.
3. **Thin column set** — the existing export omits `group_id`, `group_role`, `match_type`,
   `value_date`, `booking_date`, `aging_days`, `aging_bucket`.

This task adds a proper filter-aware download from the Results Workbench toolbar and fixes
the column set to include P6 group fields.

---

## Acceptance Criteria

- [ ] A **"Download Report"** button appears in the `ResultsWorkbench` toolbar, to the left
      of "Run AI triage"
- [ ] Clicking it downloads a CSV that reflects the analyst's **current filters** (search
      term, status dropdown, exceptions-only toggle)
- [ ] The CSV includes these columns in order:
      `case_id, psr_id, camt_id, match_type, group_id, group_role, reference, invoice,
       counterparty, internal_amount, bank_amount, variance, currency, value_date,
       booking_date, reconciliation_status, reason_code, match_confidence, rule_applied,
       exception_flag, aging_days, aging_bucket, explanation`
- [ ] Filename is `recon_report_YYYYMMDD.csv` using today's date
- [ ] The existing `/api/workspace/export/reconciliation-results` endpoint is left untouched
      (other tabs still use it)
- [ ] No pagination limit — the export returns all matching rows, not just the current page

---

## Implementation

### Step 1 — New backend endpoint (`backend/app/main.py`)

Add a new route that reuses the same filter logic as `list_cases()` but streams a CSV:

```python
@app.get("/api/reconcile/cases/export")
def export_cases(
    status: Optional[str] = None,
    exception_only: bool = False,
    search: Optional[str] = None,
    group_id: Optional[str] = None,
):
    clauses = []; params = []
    if group_id: clauses.append("group_id = ?"); params.append(group_id)
    if status == 'ai_processed':
        clauses.append("reconciliation_status IN ('AI-Assisted Suggested Match', ...)")
    elif status == 'in_transit':
        clauses.append("reconciliation_status IN ('Uncleared / In-Transit Payment', ...)")
    elif status == 'matched':
        clauses.append("reconciliation_status IN ('Matched & Settled (Auto-Close)', 'Resolved Manually')")
    elif status:
        clauses.append("reconciliation_status = ?"); params.append(status)
    if exception_only:
        clauses.append("exception_flag = 'Y' AND reconciliation_status NOT IN (...)")
    if search:
        clauses.append("(case_id LIKE ? OR psr_id LIKE ? OR camt_id LIKE ? OR reference LIKE ? OR invoice LIKE ? OR counterparty LIKE ?)")
        term = f"%{search}%"; params.extend([term] * 6)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute(
            f"SELECT * FROM recon_cases {where} ORDER BY case_id", params
        ).fetchall())
    COLS = [
        "case_id", "psr_id", "camt_id", "match_type", "group_id", "group_role",
        "reference", "invoice", "counterparty", "internal_amount", "bank_amount",
        "variance", "currency", "value_date", "booking_date",
        "reconciliation_status", "reason_code", "match_confidence", "rule_applied",
        "exception_flag", "aging_days", "aging_bucket", "explanation",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=recon_report.csv"},
    )
```

> **Note:** Place this route BEFORE `@app.get("/api/reconcile/cases/{case_id}")` so
> FastAPI does not interpret "export" as a `case_id` path segment.

### Step 2 — API client (`frontend/src/api/client.js`)

Add a URL builder that encodes current filter state:

```js
exportCasesUrl: ({ search = '', status = '', exceptionOnly = false } = {}) => {
  const qs = new URLSearchParams({ exception_only: exceptionOnly });
  if (search) qs.set('search', search);
  if (status) qs.set('status', status);
  return `${API_BASE}/api/reconcile/cases/export?${qs.toString()}`;
},
```

### Step 3 — ResultsWorkbench toolbar (`frontend/src/App.jsx`)

In `ResultsWorkbench`, add a download button next to "Run AI triage":

```jsx
<button
  className="btn secondary"
  style={{ flexShrink: 0, whiteSpace: 'nowrap' }}
  onClick={() => {
    const url = api.exportCasesUrl({ search, status: selectedStatus, exceptionOnly });
    const a = document.createElement('a');
    a.href = url;
    a.download = `recon_report_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
  }}
>
  ↓ Download Report
</button>
```

The `search`, `selectedStatus`, and `exceptionOnly` values are already in scope inside
`ResultsWorkbench` state.

---

## What NOT to change

- Do not modify `GET /api/workspace/export/reconciliation-results` or `workspace.py`
- Do not change the Workspace or Dashboards export buttons
- Do not add pagination to the export — it should always return all matching rows

---

## Gap tracker

This task closes **G4** (CSV/Excel export endpoint + UI button) from the FRS Gap Tracker in
`docs/DEVELOPER_GUIDE.md`.
