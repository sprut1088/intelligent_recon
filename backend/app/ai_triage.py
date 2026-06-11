"""
ai_triage.py — Pass 2 AI residual triage.

Tier 2b: deterministic pre-filter + sentence-transformer embedding similarity.
Returns up to Top 5 candidate CAMT matches per unmatched PSR.
Tier 2c (LLM adjudication) is implemented in a separate function in this module.
"""
from __future__ import annotations

from typing import Dict, List, Optional
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
            records with status 'Uncleared / In-Transit Payment' are used.

    Returns:
        List of candidate dicts:
        {
            psr_id, camt_id, cosine_score, zone ("clear" | "maybe"),
            psr_text, camt_text, psr_amount, camt_amount,
            psr_direction, camt_direction
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

        # Pull all CAMT entries not already linked to a matched case
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

        # Take Top 5, exclude anything below 0.60
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
                "psr_text": psr_txt,
                "camt_text": _camt_text(camt),
                "psr_amount": psr.get("amount"),
                "camt_amount": camt.get("amount"),
                "psr_direction": psr.get("direction"),
                "camt_direction": camt.get("direction"),
            })

    return candidates
