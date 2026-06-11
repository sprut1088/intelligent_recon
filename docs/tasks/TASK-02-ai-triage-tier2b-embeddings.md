# TASK-02 · Create `ai_triage.py` — Tier 2b embedding similarity with deterministic pre-filter

**Type:** Backend  
**Branch:** `feature/residual-match-ai`  
**Depends on:** TASK-01 (rapidfuzz must be installed; environment set up)  
**Blocks:** TASK-03, TASK-04  
**Effort:** ~4–6 hours

---

## Background

After Pass 1 (P1–P8) runs, a residual pool of unmatched PSR records remains. Tier 2b uses `sentence-transformers` to compute cosine similarity between text embeddings of unmatched PSR and CAMT records, producing up to **Top 5 candidate CAMT matches per PSR**.

**Critical design constraint (from mentor review):**  
Embeddings are bad at math. Do NOT embed amounts or dates — vector models treat `"105.00"` and `"1050.0"` as similar because they share characters. Numbers must be handled by a **deterministic pre-filter** that runs before any embedding is computed.

---

## Acceptance Criteria

- [ ] New file `backend/app/ai_triage.py` created
- [ ] `sentence-transformers` added to `backend/requirements.txt`
- [ ] Pre-filter correctly excludes CAMT entries that don't match direction, are outside the amount window, or are outside the date window
- [ ] Embeddings are computed on text fields only (no amounts, no dates)
- [ ] Function returns Top 5 ranked candidates per unmatched PSR, or fewer if fewer survive pre-filter
- [ ] Records with cosine similarity ≥ 0.85 are marked `"clear"`, records in 0.60–0.84 are marked `"maybe"` (for Tier 2c), records below 0.60 are excluded
- [ ] Module is importable and has no side effects on import

---

## Implementation

### Step 1 — Add dependency

In `backend/requirements.txt`, add:
```
sentence-transformers>=3.0
```

Install locally:
```bash
pip install sentence-transformers
```

### Step 2 — Create `backend/app/ai_triage.py`

```python
"""
ai_triage.py — Pass 2 AI residual triage.

Tier 2b: deterministic pre-filter + sentence-transformer embedding similarity.
Returns up to Top 5 candidate CAMT matches per unmatched PSR.
Tier 2c (LLM adjudication) is implemented in a separate function in this module.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from .config import settings
from .db import get_conn, rows_to_dicts

# Lazy-load the model so import is fast and tests don't download the model
_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _psr_text(row: Dict) -> str:
    """Text representation of a PSR record for embedding. NO amounts or dates."""
    parts = [
        row.get("reference") or "",
        row.get("invoice") or "",
        row.get("counterparty") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def _camt_text(row: Dict) -> str:
    """Text representation of a CAMT record for embedding. NO amounts or dates."""
    parts = [
        row.get("remittance") or "",
        row.get("counterparty") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def _passes_prefilter(psr: Dict, camt: Dict) -> bool:
    """
    Deterministic guard rails — must all pass before embedding is computed.
    1. Direction must match (CR↔CR, DR↔DR).
    2. Amount difference must be within MINOR_VARIANCE_TOLERANCE.
    3. Date difference must be within IN_TRANSIT_DAYS.
    """
    # Direction check
    psr_dir = (psr.get("direction") or "").upper()
    camt_dir = (camt.get("direction") or "").upper()
    if psr_dir and camt_dir and psr_dir != camt_dir:
        return False

    # Amount window
    try:
        psr_amt = float(psr.get("amount") or 0)
        camt_amt = float(camt.get("amount") or 0)
        if abs(psr_amt - camt_amt) > settings.minor_variance_tolerance:
            return False
    except (TypeError, ValueError):
        return False

    # Date window
    try:
        from datetime import date
        psr_date = date.fromisoformat(psr.get("execution_date") or "")
        camt_date = date.fromisoformat(camt.get("booking_date") or "")
        if abs((camt_date - psr_date).days) > settings.in_transit_days:
            return False
    except (TypeError, ValueError):
        pass  # If dates are missing/malformed, do not reject on date — let embeddings decide

    return True


def run_tier2b(unmatched_psr_ids: Optional[List[str]] = None) -> List[Dict]:
    """
    Tier 2b: embedding similarity for the unmatched PSR pool.

    Args:
        unmatched_psr_ids: Optional list of PSR IDs to triage. If None, all
            records with status containing 'In-Transit' or 'Uncleared' are used.

    Returns:
        List of candidate dicts:
        {
            psr_id, camt_id, cosine_score, zone ("clear" | "maybe"),
            psr_text, camt_text
        }
    """
    import numpy as np

    with get_conn() as conn:
        if unmatched_psr_ids:
            placeholders = ",".join("?" * len(unmatched_psr_ids))
            psr_rows = rows_to_dicts(conn.execute(
                f"SELECT * FROM psr_transactions WHERE id IN ({placeholders})",
                unmatched_psr_ids
            ).fetchall())
        else:
            # Pull all PSR IDs that are currently unmatched in recon_cases
            unmatched_case_rows = rows_to_dicts(conn.execute(
                """SELECT psr_id FROM recon_cases
                   WHERE reconciliation_status LIKE '%In-Transit%'
                      OR reconciliation_status LIKE '%Uncleared%'"""
            ).fetchall())
            ids = [r["psr_id"] for r in unmatched_case_rows if r["psr_id"]]
            if not ids:
                return []
            placeholders = ",".join("?" * len(ids))
            psr_rows = rows_to_dicts(conn.execute(
                f"SELECT * FROM psr_transactions WHERE id IN ({placeholders})", ids
            ).fetchall())

        # Pull all unmatched CAMT entries (those not linked to an auto-close case)
        matched_camt_ids = {
            r["camt_id"] for r in rows_to_dicts(
                conn.execute(
                    "SELECT camt_id FROM recon_cases WHERE camt_id IS NOT NULL AND camt_id != ''"
                ).fetchall()
            )
        }
        all_camt = rows_to_dicts(conn.execute("SELECT * FROM camt_transactions").fetchall())
        unmatched_camt = [c for c in all_camt if c.get("camt_id") not in matched_camt_ids]

    if not psr_rows or not unmatched_camt:
        return []

    model = _get_model()
    candidates = []

    for psr in psr_rows:
        # Step 1: deterministic pre-filter
        eligible_camt = [c for c in unmatched_camt if _passes_prefilter(psr, c)]
        if not eligible_camt:
            continue

        # Step 2: embed text fields only
        psr_txt = _psr_text(psr)
        camt_texts = [_camt_text(c) for c in eligible_camt]

        if not psr_txt:
            continue

        all_texts = [psr_txt] + camt_texts
        embeddings = model.encode(all_texts, normalize_embeddings=True)
        psr_vec = embeddings[0]
        camt_vecs = embeddings[1:]

        # Cosine similarity (vectors are normalised, so dot product = cosine)
        scores = np.dot(camt_vecs, psr_vec)

        # Take Top 5
        top_indices = np.argsort(scores)[::-1][:5]
        for idx in top_indices:
            score = float(scores[idx])
            if score < 0.60:
                break  # sorted descending — nothing below will qualify
            camt = eligible_camt[idx]
            zone = "clear" if score >= 0.85 else "maybe"
            candidates.append({
                "psr_id": psr["id"],
                "camt_id": camt["camt_id"],
                "cosine_score": round(score, 4),
                "zone": zone,
                "psr_text": _psr_text(psr),
                "camt_text": _camt_text(camt),
                "psr_amount": psr.get("amount"),
                "camt_amount": camt.get("amount"),
                "psr_direction": psr.get("direction"),
                "camt_direction": camt.get("direction"),
            })

    return candidates
```

### Step 3 — Manual smoke test

After implementing, run from `backend/`:
```bash
python -c "
import sys; sys.path.insert(0, '.')
from app.ai_triage import run_tier2b
# Requires sample data loaded in DB first (run POST /api/load-sample via the UI)
results = run_tier2b()
print(f'Candidates: {len(results)}')
for r in results[:5]:
    print(r)
"
```

---

## Files Changed

| File | Change |
|---|---|
| `backend/requirements.txt` | Add `sentence-transformers>=3.0` |
| `backend/app/ai_triage.py` | New file — Tier 2b implementation |

---

## Notes

- The model (`all-MiniLM-L6-v2`) is ~80MB, downloaded once to the local HuggingFace cache on first run. No internet required after that.
- No PII or financial data leaves the server — all embedding computation is local.
- `_get_model()` is lazy-loaded so importing the module in tests is fast.
- Tier 2c (LLM adjudication for "maybe" zone records) is a separate task (TASK-04) that adds to this same file.
