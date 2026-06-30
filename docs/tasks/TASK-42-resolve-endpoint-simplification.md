# TASK-42 · Resolve endpoint — simplify group resolution (remove member routing)

**Type:** Backend  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** TASK-40, TASK-41 (no more MEMBER rows exist in DB)  
**Blocks:** TASK-45  
**Can run in parallel with:** TASK-43, TASK-44  
**Effort:** ~1–2 hours

---

## Background

The current `resolve_case()` endpoint in `main.py` has a member→anchor routing block
that redirects a MEMBER case_id to its ANCHOR before writing the resolution. It also
performs a group-wide `UPDATE` to mark all sibling cases as resolved.

After TASK-40 and TASK-41, there are no MEMBER rows — every group has exactly one case.
The routing logic and group-wide update loop become dead code and should be removed to
keep the endpoint clean.

Additionally, for P6 cases, `selected_psr_ids` should be derived from the `psr_members`
list embedded in the case rather than from a DB siblings query. For P10, `selected_bank_ids`
should come from `camt_members`.

---

## Acceptance Criteria

- [ ] The member→anchor routing block is **removed** (no `if case["group_role"] == "MEMBER":` check)
- [ ] The group-siblings DB query (`SELECT case_id, psr_id FROM recon_cases WHERE group_id = ?`) is **removed**
- [ ] For a P6 case (`match_type = "N_TO_1"`): `selected_psr_ids` is populated from `psr_members` JSON on the case
- [ ] For a P10 case (`match_type = "1_TO_N"`): `selected_bank_ids` is populated from `camt_members` JSON on the case
- [ ] For a non-group case: behaviour unchanged — `selected_psr_ids` and `selected_bank_ids` fall back to request body values or the single case IDs
- [ ] One `recon_manual_resolution` row is written per resolve call (unchanged)
- [ ] `learning_eligible = 0` is still enforced for P6 and P10 cases (`rule_applied` starts with `"P6_"` or `"P10_"`)
- [ ] Response body retains `group_id` field (now always the `group_id` of the case, or null) — `resolved_via_anchor` and `member_case_ids` can be removed or left as empty stubs for backward-compat
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions

---

## Implementation

### Changes to `resolve_case()` in `backend/app/main.py`

**Remove** the routing block:
```python
# DELETE THIS ENTIRE BLOCK:
routed_from_member = False
if case["group_role"] == "MEMBER":
    anchor_row = conn.execute(
        "SELECT * FROM recon_cases WHERE group_id = ? AND group_role = 'ANCHOR'",
        (case["group_id"],),
    ).fetchone()
    if anchor_row:
        routed_from_member = True
        case = anchor_row
```

**Remove** the sibling fetch:
```python
# DELETE THIS ENTIRE BLOCK:
group_id       = case["group_id"]
group_case_ids = []
group_psr_ids  = []
if group_id:
    sibling_rows = conn.execute(
        "SELECT case_id, psr_id FROM recon_cases WHERE group_id = ?", (group_id,)
    ).fetchall()
    group_case_ids = [r["case_id"] for r in sibling_rows]
    group_psr_ids  = [r["psr_id"]  for r in sibling_rows if r["psr_id"]]
```

**Replace** `selected_psr` / `selected_bank` derivation with:
```python
group_id = case["group_id"]

# Derive PSR ids: from embedded members list (P6) or request / single case (all others)
psr_members   = json.loads(case["psr_members_json"])  if case["psr_members_json"]  else None
camt_members  = json.loads(case["camt_members_json"]) if case["camt_members_json"] else None

selected_psr = (
    [m["psr_id"] for m in psr_members]   if psr_members
    else request.selected_psr_ids or ([case["psr_id"]] if case["psr_id"] else [])
)
selected_bank = (
    [m["camt_id"] for m in camt_members] if camt_members
    else request.selected_bank_ids or ([case["camt_id"]] if case["camt_id"] else [])
)
```

**Update** `is_p6_case` to cover P10 as well:
```python
is_group_case = (case["rule_applied"] or "").startswith(("P6_", "P10_"))
effective_learning_eligible = False if (is_override or is_group_case) else request.learning_eligible
```

**Simplify** the final UPDATE (no group-wide loop needed — just update the single case):
```python
conn.execute(
    "UPDATE recon_cases SET reconciliation_status='Resolved Manually', reason_code=?, "
    "exception_flag='N', explanation=?, updated_at=CURRENT_TIMESTAMP WHERE case_id=?",
    (request.reason_code, resolution_expl, case["case_id"]),
)
mark_workflow_resolved(conn, case["case_id"], updated_by="prototype_user",
                       comment=f"Resolved as {request.resolution_type}")
```
