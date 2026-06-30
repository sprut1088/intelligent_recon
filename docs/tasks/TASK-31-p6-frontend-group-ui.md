# TASK-31 · Frontend — group badge in ResultTable and EvidenceDrawer sibling panel

**Type:** Frontend  
**Branch:** `feat/one-2-many`  
**Depends on:** TASK-28 (P6 cases in DB), TASK-29 (group-aware resolve endpoint)  
**Blocks:** Nothing  
**Can run in parallel with:** TASK-30, TASK-32  
**Effort:** ~3–4 hours

---

## Background

P6 group cases appear in `recon_cases` with `match_type = "N_TO_1"` and
`group_role = "ANCHOR"` or `"MEMBER"`. The frontend needs two changes:

1. **ResultTable** — show a "N→1" pill badge on every P6 row so analysts can see at a glance
   that a row belongs to a group
2. **EvidenceDrawer** — when a P6 case is opened, show a "Group members" section listing all
   sibling PSR rows before the suggested actions panel; clicking a sibling navigates to it

The resolve flow requires no changes — the existing `ManualResolveModal` already works because
the backend (TASK-29) handles group routing transparently. The modal should pre-populate the
PSR IDs from the `suggestions[0].group_psr_ids` field that TASK-28 adds to anchor rows.

---

## Acceptance Criteria

### ResultTable badge

- [ ] Every row with `match_type === "N_TO_1"` displays a small pill badge showing
      `"N→1"` in the confidence/status area
- [ ] Anchor rows (`group_role === "ANCHOR"`) show badge text `"N→1 anchor"`
- [ ] Member rows (`group_role === "MEMBER"`) show badge text `"N→1 member"`
- [ ] Badge colour: use the existing blue-light style (same as "Suggested Match – Enhanced Fuzzy")
- [ ] Badge does not break existing layout for non-group rows
- [ ] Clicking the row still opens the EvidenceDrawer as normal

### EvidenceDrawer sibling panel

- [ ] When a P6 case is opened (`match_type === "N_TO_1"`), a "Group members" section
      appears above the "Suggested actions" section
- [ ] Section header: `"Group settlement — N PSRs → 1 bank entry"` (N = count of siblings)
- [ ] Section lists each PSR in the group: `psr_id`, `internal_amount`, `execution_date`,
      `group_role` (ANCHOR / MEMBER)
- [ ] Current row is highlighted / marked "(this case)"
- [ ] Clicking a sibling row calls `onSelectCase(sibling_case_id)` to navigate to it
- [ ] If sibling data is not yet loaded, a lightweight loading state is shown
- [ ] Section is hidden for non-group cases (no change to existing drawer for 1:1 cases)

### Resolve modal

- [ ] When opening the resolve modal from a P6 anchor case, `selected_psr_ids` is
      pre-populated from `suggestions[0].group_psr_ids` (the full group PSR list)
- [ ] The resolve modal's PSR IDs field label changes to `"PSR IDs (group)"` when more than
      one PSR ID is present

---

## Implementation

### Step 1 — Group badge in ResultTable rows (`frontend/src/App.jsx`)

Find the result row render function inside `ResultsWorkbench`. Locate where
`reconciliation_status` and `match_confidence` are shown and add:

```jsx
{row.match_type === "N_TO_1" && (
  <span className="badge badge-group" title={`Group: ${row.group_id}`}>
    {row.group_role === "ANCHOR" ? "N→1 anchor" : "N→1 member"}
  </span>
)}
```

Add the following to `frontend/src/App.css` (or the relevant styles file):

```css
.badge-group {
  background: #dbeafe;   /* blue-100 */
  color: #1e40af;        /* blue-800 */
  border: 1px solid #93c5fd;
  border-radius: 4px;
  font-size: 0.7rem;
  padding: 1px 5px;
  margin-left: 4px;
  vertical-align: middle;
  font-weight: 600;
}
```

### Step 2 — Load sibling cases in EvidenceDrawer

The drawer currently loads `GET /api/reconcile/cases/{case_id}`. The response already contains
`case.group_id`. When `group_id` is non-null, fetch sibling cases:

```js
// In the useEffect that loads case detail, add after the primary fetch:
if (caseDetail.case.group_id) {
  const siblingsRes = await api.getCases({
    search: caseDetail.case.group_id,   // group_id stored in searchable fields? 
    limit: 20,
  });
  // OR: use a dedicated query param when TASK-29 adds group_id filtering
  setSiblingCases(siblingsRes.items.filter(c => c.group_id === caseDetail.case.group_id));
}
```

> **Note:** The `GET /api/reconcile/cases` endpoint does not currently support filtering by
> `group_id`. The simplest approach is to search by the `group_id` string (it will match
> `case_id LIKE ?` on the `GRP-` prefix). Alternatively, TASK-32 can add `group_id` as
> an explicit query param — coordinate with that task if needed.

A temporary fallback: store `group_id` in the `match_key` column so the existing `search`
filter picks it up. (Verify `match_key = camt.ntry_id` for anchor rows — if so, use
`feature_snapshot.group_id` from the already-loaded case detail instead.)

**Simplest correct approach**: add `group_id` as an optional query param to
`GET /api/reconcile/cases` in `main.py` (one-line change):

```python
# In list_cases(), add after existing filter clauses:
if group_id:
    clauses.append("group_id = ?"); params.append(group_id)
```

And the function signature:
```python
def list_cases(..., group_id: Optional[str] = None) -> dict:
```

### Step 3 — Group section in EvidenceDrawer JSX

Inside the EvidenceDrawer component, add before the suggestions/actions section:

```jsx
{caseDetail?.case?.match_type === "N_TO_1" && (
  <div className="group-panel">
    <h4>Group settlement — {siblingCases.length} PSRs → 1 bank entry</h4>
    <table className="group-sibling-table">
      <thead>
        <tr>
          <th>Case</th><th>PSR ID</th><th>Amount</th><th>Date</th><th>Role</th>
        </tr>
      </thead>
      <tbody>
        {siblingCases.map(sib => (
          <tr
            key={sib.case_id}
            className={sib.case_id === caseDetail.case.case_id ? "current-row" : "sibling-row"}
            onClick={() => sib.case_id !== caseDetail.case.case_id && onSelectCase(sib.case_id)}
          >
            <td>{sib.case_id === caseDetail.case.case_id ? `${sib.case_id} (this)` : sib.case_id}</td>
            <td>{sib.psr_id}</td>
            <td>{sib.internal_amount?.toFixed(2)}</td>
            <td>{sib.value_date}</td>
            <td>
              <span className={`badge badge-group`}>{sib.group_role}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)}
```

Add minimal styles:
```css
.group-panel {
  border: 1px solid #93c5fd;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: #eff6ff;
}
.group-panel h4 { margin: 0 0 8px; color: #1e40af; font-size: 0.85rem; }
.group-sibling-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.group-sibling-table td, .group-sibling-table th { padding: 4px 8px; border-bottom: 1px solid #dbeafe; }
.sibling-row { cursor: pointer; }
.sibling-row:hover { background: #dbeafe; }
.current-row { background: #bfdbfe; font-weight: 600; }
```

### Step 4 — Pre-populate resolve modal PSR IDs

In `ManualResolveModal`, find where `selected_psr_ids` is initialised and add:

```js
// When the case is a P6 anchor, pre-populate all group PSR IDs
const groupPsrIds = caseData?.suggestions?.[0]?.group_psr_ids;
const [selectedPsrIds, setSelectedPsrIds] = useState(
  groupPsrIds && groupPsrIds.length > 1 ? groupPsrIds : [caseData?.psr_id].filter(Boolean)
);
```

Update the PSR IDs field label:
```jsx
<label>{selectedPsrIds.length > 1 ? "PSR IDs (group)" : "PSR ID"}</label>
```

---

## Verification

1. Load sample data with P6 groups (run `POST /api/load-sample`)
2. Open Results Workbench — confirm N→1 badges visible on P6 rows
3. Click an anchor row → EvidenceDrawer opens → Group members section shows siblings
4. Click a member row in the sibling panel → drawer navigates to that case
5. Click "Resolve" on an anchor → modal shows all group PSR IDs pre-filled
6. Submit resolution → all sibling rows disappear from exception queue
