# TASK-30 · P10 Honesty Fix — rename candidate label and add log line

**Type:** Backend  
**Branch:** `feat/one-2-many`  
**Depends on:** None — independent cosmetic fix  
**Blocks:** Nothing  
**Can run in parallel with:** TASK-26, TASK-27, TASK-28, TASK-29  
**Effort:** ~30 minutes

---

## Background

`learning.py` maps `BANK_BATCH_AGGREGATION` resolution signals to a candidate pattern named
`"Bank Batch Settlement Grouping"` with `pattern_key = "P10_BANK_BATCH_GROUPING"`.

When this candidate is approved, `approve_candidate()` inserts a row into `recon_pattern_registry`
as `status='ACTIVE'` — but `reconcile_transactions()` has no execution branch for P10.
The approved pattern **does nothing**.

This was already a known issue (Developer Guide Gap G7). Now that P6 ships as the actual
execution path for batch grouping, P10 approval should be honest about what it represents:
a signal to **loosen P6's parameters**, not a standalone pattern.

This task makes two small changes:
1. Renames the candidate label to describe its intent
2. Adds a one-line `logger.info` in `approve_candidate()` when a P10-family candidate is approved

---

## Acceptance Criteria

- [ ] `pattern_name_for()` returns `"Bank Batch Settlement — Loosen P6 Parameters"` for
      `BANK_BATCH_AGGREGATION` / `one_to_many` signals (was: `"Bank Batch Settlement Grouping"`)
- [ ] `proposed_rule_for()` updated to describe the intended P6 parameter relaxation mechanism
- [ ] `approve_candidate()` logs an info message when approving a candidate whose name contains
      `"Bank Batch Settlement"`, explaining the pattern is recorded but not yet wired
- [ ] Existing tests pass
- [ ] Learning tab in the UI still shows the candidate and can approve it (no functional break)

---

## Implementation

### Step 1 — Rename in `pattern_name_for()` in `backend/app/learning.py`

```python
# Old:
if reason_code == "BANK_BATCH_AGGREGATION" or "one_to_many" in fields_used:
    return "Bank Batch Settlement Grouping"

# New:
if reason_code == "BANK_BATCH_AGGREGATION" or "one_to_many" in fields_used:
    return "Bank Batch Settlement — Loosen P6 Parameters"
```

### Step 2 — Update `proposed_rule_for()` in `backend/app/learning.py`

```python
# Old:
if "Bank Batch" in pattern_name:
    return {
        "pattern_key": "P10_BANK_BATCH_GROUPING",
        "logic": ["group PSR payments by booking date/reference family",
                  "compare sum to CAMT bank entry amount"],
        "required_fields": ["amount_sum", "date", "reference_family"],
    }

# New:
if "Bank Batch Settlement" in pattern_name:
    return {
        "pattern_key":  "P10_BANK_BATCH_GROUPING",
        "intent":       "Loosen P6 one-to-many matching parameters",
        "mechanism":    "Reduce P6 counterparty_threshold or raise max_group_size in pattern_rule_json",
        "current_p6_defaults": {
            "counterparty_threshold": 0.85,
            "max_group_size": 6,
            "date_window_days": 3,
        },
        "proposed_relaxation": "Lower counterparty_threshold toward 0.75 based on confirmed alias patterns",
        "execution_status": "NOT_WIRED — approving this candidate records the intent but does not "
                            "automatically adjust P6 parameters. Manual config change required.",
        "required_fields": ["amount_sum", "date", "reference_family"],
    }
```

### Step 3 — Add log line in `approve_candidate()` in `backend/app/learning.py`

After the registry insert in `approve_candidate()`, add:

```python
    # Honesty log for P10-family approvals (P6 is the actual executor)
    if "Bank Batch Settlement" in cand["pattern_name"]:
        logger.info(
            "P10 candidate '%s' approved and recorded in registry (pattern_id=%s). "
            "NOTE: this does not automatically adjust P6 parameters — see TASK-30 / Gap G7.",
            cand["pattern_name"], pattern_id,
        )
```

---

## Verification

```bash
cd backend
python -c "
from app.learning import pattern_name_for, proposed_rule_for
name = pattern_name_for('BANK_BATCH_AGGREGATION', [])
assert 'Loosen P6 Parameters' in name, f'Unexpected name: {name}'
rule = proposed_rule_for(name, 'BANK_BATCH_AGGREGATION', [])
assert rule.get('intent') == 'Loosen P6 one-to-many matching parameters'
print('P10 rename: OK')
print('Name:', name)
"

python -m pytest backend/tests/ -v
```
