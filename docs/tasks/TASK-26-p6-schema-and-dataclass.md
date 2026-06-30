# TASK-26 · P6 Schema — add `group_id` / `group_role` to DB and `ReconCase`

**Type:** Backend  
**Branch:** `feat/one-2-many`  
**Depends on:** None — first task, pick up immediately  
**Blocks:** TASK-27, TASK-28  
**Can run in parallel with:** TASK-30  
**Effort:** ~1–2 hours

---

## Background

P6 one-to-many matching produces groups of N PSR transactions linked to a single CAMT entry.
The chosen data model is **Option B**: individual `recon_cases` rows for every PSR in the group,
all sharing a `group_id` string and a `group_role` of `ANCHOR` or `MEMBER`.

This task lays the data foundation — DB columns, the `ReconCase` dataclass, the insert SQL, and
the updated P6 registry seed — before any algorithm or wiring work starts.

---

## Acceptance Criteria

- [ ] `recon_cases` table gains two nullable columns: `group_id TEXT` and `group_role TEXT`
- [ ] Migration is **idempotent**: running `init_db()` on an existing DB doesn't error
- [ ] `ReconCase` dataclass has `group_id: Optional[str]` and `group_role: Optional[str]`
- [ ] `case_to_db_tuple()` emits both new fields (nulls for all existing 1:1 cases)
- [ ] `CASE_INSERT_SQL` in **both** `loader.py` and `ingestion.py` includes the two new columns
- [ ] P6 seed in `DEFAULT_PATTERNS` contains the full `pattern_rule_json` with all config knobs
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions

---

## Implementation

### Step 1 — Add columns to `SCHEMA` in `backend/app/db.py`

Find the `recon_cases` CREATE TABLE line and append the two columns before the closing `)`:

```python
# Before (end of recon_cases line):
# ...suggestions_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

# After:
# ...suggestions_json TEXT, group_id TEXT, group_role TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
```

### Step 2 — Add migration guard in `init_db()` in `backend/app/db.py`

`CREATE TABLE IF NOT EXISTS` does not add new columns to an existing table.
Add an idempotent ALTER TABLE block **after** `conn.executescript(SCHEMA)`:

```python
def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        seed_default_patterns(conn)
        # Idempotent column migrations — safe to run on existing DBs
        for col, col_def in [
            ("group_id",   "TEXT"),
            ("group_role", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE recon_cases ADD COLUMN {col} {col_def}")
            except Exception:
                pass  # column already exists
        conn.commit()
```

### Step 3 — Update P6 seed in `DEFAULT_PATTERNS` in `backend/app/db.py`

Replace the existing sparse P6 rule JSON with the full config knob set:

```python
# Old:
("P6", "One-to-Many Bank Settlement", "SEED",
 {"fields": ["pmt_ref", "invoice", "amount_sum"]},
 "ACTIVE", "SUGGESTION", 0.85),

# New:
("P6", "One-to-Many Bank Settlement", "SEED",
 {
     "fields": ["pmt_ref", "invoice", "amount_sum"],
     "counterparty_threshold": 0.85,       # input filter: min similarity to include PSR in candidate pool
     "max_group_size": 6,                  # max PSRs per group (subset-sum cap)
     "date_window_days": 3,                # PSR execution_date vs CAMT booking_date window
     "variance_subpass_enabled": True,     # run tolerance sub-pass for small groups
     "variance_subpass_max_group_size": 3, # only try variance sub-pass when group size ≤ this
 },
 "ACTIVE", "SUGGESTION", 0.85),           # registry confidence_threshold = output gate
```

> Note: `counterparty_threshold` (input similarity floor) and `confidence_threshold` (output gate)
> are both 0.85 but are accessed via different paths:
> - `pattern_rule_value(config, "P6", "counterparty_threshold", 0.85)` — used by the algorithm
> - `row["confidence_threshold"]` — used by the engine to decide whether to emit the case

### Step 4 — Update `ReconCase` dataclass in `backend/app/reconciliation.py`

Add the two optional fields at the end of the dataclass definition:

```python
@dataclass
class ReconCase:
    case_id: str; match_key: str; psr_id: str; camt_id: str; reference: str; invoice: str; counterparty: str
    internal_amount: Optional[float]; bank_amount: Optional[float]; variance: Optional[float]; currency: str; value_date: str; booking_date: str
    reconciliation_status: str; reason_code: str; match_type: str; match_confidence: int; aging_days: int; aging_bucket: str; rule_applied: str; exception_flag: str
    explanation: str; feature_snapshot: Dict; suggestions: List[Dict]
    group_id: Optional[str] = None
    group_role: Optional[str] = None
```

### Step 5 — Update `case_to_db_tuple()` in `backend/app/reconciliation.py`

Append the two new fields to the returned tuple:

```python
def case_to_db_tuple(case: ReconCase) -> tuple:
    p = asdict(case)
    return (
        p["case_id"], p["match_key"], p["psr_id"], p["camt_id"],
        p["reference"], p["invoice"], p["counterparty"],
        p["internal_amount"], p["bank_amount"], p["variance"],
        p["currency"], p["value_date"], p["booking_date"],
        p["reconciliation_status"], p["reason_code"], p["match_type"],
        p["match_confidence"], p["aging_days"], p["aging_bucket"],
        p["rule_applied"], p["exception_flag"], p["explanation"],
        json.dumps(p["feature_snapshot"]), json.dumps(p["suggestions"]),
        p["group_id"], p["group_role"],
    )
```

### Step 6 — Update `CASE_INSERT_SQL` in **both** `loader.py` and `ingestion.py`

Both files define the same `CASE_INSERT_SQL` constant. Add the two columns and two `?` placeholders:

```python
CASE_INSERT_SQL = """
INSERT INTO recon_cases
(case_id, match_key, psr_id, camt_id, reference, invoice, counterparty, internal_amount, bank_amount,
 variance, currency, value_date, booking_date, reconciliation_status, reason_code, match_type,
 match_confidence, aging_days, aging_bucket, rule_applied, exception_flag, explanation,
 feature_snapshot_json, suggestions_json, group_id, group_role)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
```

---

## Verification

```bash
cd backend
python -c "from app.db import init_db; init_db(); print('OK')"
python -c "
from app.db import get_conn
with get_conn() as conn:
    cols = [row[1] for row in conn.execute('PRAGMA table_info(recon_cases)').fetchall()]
    assert 'group_id' in cols and 'group_role' in cols, f'Missing columns. Got: {cols}'
    print('Columns present:', [c for c in cols if c in ('group_id','group_role')])
"
python -m pytest backend/tests/ -v
```
