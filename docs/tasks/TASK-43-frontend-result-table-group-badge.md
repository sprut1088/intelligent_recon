# TASK-43 · Frontend — ResultTable: single group row + correct badges for N→1 and 1→N

**Type:** Frontend  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** TASK-40, TASK-41 (API now returns one case per group)  
**Blocks:** TASK-45  
**Can run in parallel with:** TASK-42, TASK-44  
**Effort:** ~1–2 hours

---

## Background

Currently:
- The ResultTable shows one row per case. For a 3-PSR P6 group that means 3 rows — noisy.
- The badge only handles `match_type === "N_TO_1"`. P10 (`1_TO_N`) cases have no badge.

After TASK-40 and TASK-41, each group/split is a single case, so the ResultTable row count
is already correct. This task updates the badge and the sub-text to properly represent both
group types, and removes any client-side logic that used to suppress or reformat member rows.

---

## Acceptance Criteria

- [ ] `N_TO_1` case shows badge: `N→1 · 3 PSRs` (where 3 = `psr_members.length`)
- [ ] `1_TO_N` case shows badge: `1→N · 2 CAMTs` (where 2 = `camt_members.length`)
- [ ] Badge for both types uses the existing `badge-group` CSS class (teal style)
- [ ] Sub-text under the case ID shows primary PSR ID / primary CAMT ID (same as today for 1:1 cases)
- [ ] No code remains that checks `group_role === "ANCHOR"` or `group_role === "MEMBER"` in the ResultTable cell
- [ ] `python -m pytest` (frontend: `npm run build`) produces no new errors

---

## Implementation

### Changes to `frontend/src/App.jsx` — ResultTable row cell

Find the existing badge render (around line 585):

```jsx
// BEFORE:
{r.match_type === "N_TO_1" && (
  <span className="badge badge-group" title={`Group: ${r.group_id}`}>
    {r.group_role === "ANCHOR" ? "N→1 anchor" : "N→1 member"}
  </span>
)}
```

Replace with:

```jsx
// AFTER:
{r.match_type === "N_TO_1" && (
  <span className="badge badge-group" title={`Group: ${r.group_id}`}>
    N→1 · {r.psr_members?.length ?? '?'} PSRs
  </span>
)}
{r.match_type === "1_TO_N" && (
  <span className="badge badge-group" title={`Split: ${r.group_id}`}>
    1→N · {r.camt_members?.length ?? '?'} CAMTs
  </span>
)}
```

No other changes are needed in the ResultTable — the row count reduction happens
automatically because MEMBER rows no longer exist in the API response.
