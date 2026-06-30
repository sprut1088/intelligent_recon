# TASK-39 · Group-case consolidation — DB schema + `ReconCase` dataclass

**Type:** Backend  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** None — first task, pick up immediately  
**Blocks:** TASK-40, TASK-41  
**Can run in parallel with:** Nothing (foundation for the whole branch)  
**Effort:** ~1–2 hours

---

## Background

The current P6 (N PSR → 1 CAMT) and P10 (1 PSR → N CAMT) implementations each emit one
`recon_cases` row **per transaction** (PSR or CAMT) in the group, using `group_role = ANCHOR |
MEMBER` to link them. This causes:

- Inflated case counts (3 rows for a 3-PSR group instead of 1)
- Misleading amounts on anchor/member rows
- No group panel at all for P10 in the UI

The fix is a **single case per group**, with the member transactions embedded as JSON.  
This task adds the two new columns and updates the `ReconCase` dataclass. No algorithm or
endpoint logic is changed here.

---

## Acceptance Criteria

- [ ] `recon_cases` table has two new nullable columns: `psr_members_json TEXT` and `camt_members_json TEXT`
- [ ] Migration is **idempotent**: `init_db()` on an existing DB adds the columns silently and does not error
- [ ] `ReconCase` dataclass has `psr_members: Optional[List[Dict]] = None` and `camt_members: Optional[List[Dict]] = None`
- [ ] `CASE_INSERT_SQL` in `main.py` (and anywhere else cases are inserted) includes the two new columns
- [ ] `row_to_dict()` in `db.py` automatically deserialises both new `_json` columns (it already does this for any `*_json` suffix — verify this covers the new columns)
- [ ] `group_id` and `group_role` columns are **retained** on the table for backward-compat (they will be removed in a follow-up once all readers are updated)
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions

---

## Implementation

### 1 — Add columns to `SCHEMA` in `backend/app/db.py`

Append `psr_members_json TEXT` and `camt_members_json TEXT` before `created_at` on the `recon_cases` CREATE TABLE line:

```sql
-- existing end of the line:
... group_id TEXT, group_role TEXT, created_at TEXT ...

-- becomes:
... group_id TEXT, group_role TEXT, psr_members_json TEXT, camt_members_json TEXT, created_at TEXT ...
```

### 2 — Add idempotent migration in `init_db()` in `backend/app/db.py`

Extend the existing `for col, col_def in [...]` loop:

```python
for col, col_def in [
    ("group_id",          "TEXT"),
    ("group_role",        "TEXT"),
    ("psr_members_json",  "TEXT"),   # NEW
    ("camt_members_json", "TEXT"),   # NEW
]:
    try:
        conn.execute(f"ALTER TABLE recon_cases ADD COLUMN {col} {col_def}")
    except Exception:
        pass  # column already exists
```

### 3 — Update `ReconCase` dataclass in `backend/app/reconciliation.py`

```python
@dataclass
class ReconCase:
    # ... existing fields unchanged ...
    group_id:       Optional[str]        = None
    group_role:     Optional[str]        = None
    psr_members:    Optional[List[Dict]] = None   # NEW — populated by P6
    camt_members:   Optional[List[Dict]] = None   # NEW — populated by P10
```

Each member dict shape:
- **P6 psr_members entry:** `{"psr_id": str, "amount": float, "reference": str, "date": str}`
- **P10 camt_members entry:** `{"camt_id": str, "ntry_id": str, "amount": float, "date": str}`

### 4 — Update `CASE_INSERT_SQL` in `backend/app/main.py`

Add the two new columns to the INSERT statement. Pass `json_dumps(rc.psr_members)` and
`json_dumps(rc.camt_members)` (both default to `None` → stored as SQL NULL for non-group cases).

### 5 — Verify `row_to_dict()` auto-deserialisation

`db.py::row_to_dict()` already strips `_json` suffix and parses any key ending in `_json`.
Confirm `psr_members_json` and `camt_members_json` are therefore automatically exposed as
`psr_members` and `camt_members` in all API responses. No additional mapping needed.
