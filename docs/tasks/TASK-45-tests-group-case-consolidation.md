# TASK-45 · Tests — update P6 and P10 tests for single-case model

**Type:** Backend (tests)  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** TASK-40, TASK-41, TASK-42  
**Blocks:** Nothing (final task in the branch)  
**Can run in parallel with:** Nothing  
**Effort:** ~2–3 hours

---

## Background

After TASK-40 and TASK-41, the P6 and P10 algorithms emit one case per group/split instead
of N. The existing tests assert on the old multi-case model (checking for ANCHOR + MEMBER
rows, checking sibling routing in the resolve endpoint, checking that `bank_amount` is null
on member rows, etc.) and will fail against the new implementation.

This task updates those tests to reflect the consolidated model and adds new assertions for
the embedded `psr_members` and `camt_members` payloads.

---

## Acceptance Criteria

- [ ] `python -m pytest backend/tests/ -v` passes with **zero failures**
- [ ] `test_p6_one_to_many.py` updated: all group scenarios assert exactly **1 case** per group
- [ ] `test_p6_one_to_many.py` updated: member routing test removed (no MEMBER rows exist)
- [ ] `test_p6_partitioning.py` updated: case count assertions halved for multi-PSR groups
- [ ] `test_p10_split_settlement.py` updated: all split scenarios assert exactly **1 case** per split
- [ ] New assertions added:
  - `case.psr_members` is a list of dicts with the correct `psr_id`, `amount`, `reference`, `date` for each P6 member
  - `case.camt_members` is a list of dicts with the correct `camt_id`, `ntry_id`, `amount`, `date` for each P10 member
  - `case.group_role == "GROUP"` for all consolidated cases
  - `case.internal_amount` equals the group sum (P6) or individual PSR amount (P10)
  - `case.bank_amount` is never `None` on any group/split case
  - `case.variance` is never `None` on any group/split case
- [ ] `test_cascade_order.py` updated: any assertion on case counts that included MEMBER rows is corrected

---

## Implementation

### Changes to `backend/tests/test_p6_one_to_many.py`

**Scenario 1 — Happy path (3 PSRs → 1 CAMT):**
```python
# OLD: assert len(p6_cases) == 3  (1 anchor + 2 members)
# NEW:
assert len(p6_cases) == 1
case = p6_cases[0]
assert case.group_role == "GROUP"
assert case.match_type == "N_TO_1"
assert len(case.psr_members) == 3
assert case.psr_members[0]["psr_id"] == <first_psr_id>
assert case.bank_amount is not None
assert case.variance is not None
# internal_amount = group sum
assert abs(case.internal_amount - sum(p.amount for p in psrs)) < 0.01
```

**Remove Scenario 6 — Resolve routing (member → anchor):**
This scenario tested that resolving a MEMBER case_id routes to the anchor. With no MEMBER
rows, it is no longer applicable. Delete the test.

**Add new scenario — psr_members content:**
```python
def test_p6_psr_members_content():
    """psr_members list carries correct per-PSR detail."""
    # setup 2 PSRs + 1 CAMT where psr1.amount + psr2.amount == camt.amount
    ...
    assert len(case.psr_members) == 2
    psr_ids = {m["psr_id"] for m in case.psr_members}
    assert psr_ids == {psr1.id, psr2.id}
    amounts = {m["psr_id"]: m["amount"] for m in case.psr_members}
    assert amounts[psr1.id] == psr1.amount
    assert amounts[psr2.id] == psr2.amount
```

### Changes to `backend/tests/test_p10_split_settlement.py`

```python
# OLD: assert len(split_cases) == 2  (1 anchor + 1 member)
# NEW:
assert len(split_cases) == 1
case = split_cases[0]
assert case.group_role == "GROUP"
assert case.match_type == "1_TO_N"
assert len(case.camt_members) == 2
assert case.internal_amount == psr.amount
assert abs(case.bank_amount - sum(c.amount for c in camts)) < 0.01
assert case.variance is not None
# camt_members content
amounts = {m["camt_id"]: m["amount"] for m in case.camt_members}
assert amounts[camt1.camt_id] == camt1.amount
assert amounts[camt2.camt_id] == camt2.amount
```

### Changes to `backend/tests/test_cascade_order.py`

Audit any `len(cases)` or `len(p6_cases)` assertions. For each multi-PSR P6 scenario,
reduce the expected count by `(group_size - 1)`. For each multi-CAMT P10 scenario,
reduce by `(split_size - 1)`.

### Changes to `backend/tests/test_p6_partitioning.py`

Same audit: update expected case counts for cross-partition tests where multiple groups
are expected. Each group now contributes 1 case instead of N.
