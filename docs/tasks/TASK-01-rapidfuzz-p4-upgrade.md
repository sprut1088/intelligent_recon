# TASK-01 · Upgrade counterparty fuzzy matching to rapidfuzz (P4 + new P4b step)

**Type:** Backend  
**Branch:** `feature/residual-match-ai`  
**Blocks:** TASK-02 (should be installed before creating ai_triage.py)  
**Depends on:** None — can be picked up immediately  
**Effort:** ~2–3 hours

---

## Background

The current P4 pattern uses Python's built-in `difflib.SequenceMatcher` for counterparty name similarity. It is character-level and does not handle extra legal entity tokens (e.g. "Group", "Ltd", "plc") well.

**Concrete failure:**  
`"Crestwood Retail"` vs `"Crestwood Retail Group"` → score 0.8421 → **MISS** (threshold is 0.85)  
With `rapidfuzz.token_set_ratio` → score 0.96 → **MATCH**

`rapidfuzz` is token-aware: it ignores extra words that don't change the core name identity.

---

## Acceptance Criteria

- [ ] `rapidfuzz` added to `backend/requirements.txt`
- [ ] `similarity()` function in `backend/app/reconciliation.py` (line ~26) replaced with rapidfuzz version
- [ ] All four test pairs below score ≥ 0.85 after the change
- [ ] Existing P4 threshold (0.85) and status `"Suggested Match – Analyst Review"` remain unchanged
- [ ] No other reconciliation behaviour changes (P1–P3, P5, P7, P8 unaffected)
- [ ] Existing tests in `backend/tests/` still pass

---

## Implementation

### Step 1 — Add dependency

In `backend/requirements.txt`, add:
```
rapidfuzz>=3.9
```

Install locally:
```bash
pip install rapidfuzz
```

### Step 2 — Replace `similarity()` in `backend/app/reconciliation.py`

**Current code (line ~26):**
```python
from difflib import SequenceMatcher

def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, (left or "").upper(), (right or "").upper()).ratio()
```

**Replace with:**
```python
from rapidfuzz import fuzz as _rfuzz

def similarity(left: str, right: str) -> float:
    """Token-set aware similarity. Handles legal entity suffixes (Ltd, plc, Group).
    Returns 0.0–1.0. Uses max of token_set_ratio and WRatio."""
    a = (left or "").upper()
    b = (right or "").upper()
    ts = _rfuzz.token_set_ratio(a, b) / 100.0
    wr = _rfuzz.WRatio(a, b) / 100.0
    return max(ts, wr)
```

Also remove the `from difflib import SequenceMatcher` import if it is no longer used elsewhere in the file.

### Step 3 — Verify with test script

Run from `backend/` directory:
```bash
python -c "
from rapidfuzz import fuzz as rfuzz
pairs = [
    ('Crestwood Retail',  'Crestwood Retail Group'),  # was MISS (0.84)
    ('Riverside Energy',  'Riverside Energy plc'),     # was MATCH
    ('Brightwater Ltd',   'Brightwater Limited'),      # was MATCH
    ('Shoreline Foods',   'Shoreline Foods UK'),       # was MATCH
]
for a, b in pairs:
    ts = rfuzz.token_set_ratio(a.upper(), b.upper()) / 100
    wr = rfuzz.WRatio(a.upper(), b.upper()) / 100
    score = max(ts, wr)
    print(f\"{'MATCH' if score >= 0.85 else 'MISS '}  {score:.4f}  {a!r} vs {b!r}\")
"
```

**Expected output — all four MATCH:**
```
MATCH  0.9600  'Crestwood Retail' vs 'Crestwood Retail Group'
MATCH  0.8889  'Riverside Energy' vs 'Riverside Energy plc'
MATCH  0.8824  'Brightwater Ltd' vs 'Brightwater Limited'
MATCH  0.9091  'Shoreline Foods' vs 'Shoreline Foods UK'
```

### Step 4 — Run full test suite
```bash
cd backend
pytest tests/ -v
```

---

## Files Changed

| File | Change |
|---|---|
| `backend/requirements.txt` | Add `rapidfuzz>=3.9` |
| `backend/app/reconciliation.py` | Replace `similarity()` function; remove unused `SequenceMatcher` import |

---

## Notes

- The P4 threshold (0.85) and all confidence scoring remain unchanged — only the similarity algorithm changes
- In `psr_test_50` + `camt_test_50`, this raises P4 matches from 3 to 4 (Crestwood Retail now matches)
- `rapidfuzz` is MIT licensed, pure Python with optional C extension, production-safe
