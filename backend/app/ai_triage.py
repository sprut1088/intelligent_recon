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
        import os
        os.environ.setdefault("HF_HUB_DISABLE_SSL_VERIFICATION", "1")
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

        # Pull all CAMT entries not already linked to a matched PSR-CAMT case.
        # Exclude only rows where BOTH psr_id and camt_id are present — bank-only
        # items (psr_id IS NULL) must remain available as AI triage candidates.
        matched_camt_ids = {
            r["camt_id"] for r in rows_to_dicts(
                conn.execute(
                    """SELECT camt_id FROM recon_cases
                       WHERE camt_id IS NOT NULL AND camt_id != ''
                         AND psr_id  IS NOT NULL AND psr_id  != ''"""
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


def run_tier2c(maybe_candidates: List[Dict]) -> List[Dict]:
    """
    Tier 2c: LLM adjudication for 'maybe' zone records via OpenRouter.

    For each unique PSR in maybe_candidates, sends one LLM call with
    that PSR + its Top 5 CAMT candidates. Updates recon_cases in-place.

    Returns list of LLM decision dicts. Silently skips if OPENROUTER_API_KEY
    is not set.
    """
    import os
    import json
    import logging

    logger = logging.getLogger(__name__)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — Tier 2c LLM adjudication skipped.")
        return []

    from openai import OpenAI
    from collections import defaultdict

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    # Group candidates by PSR ID, keep Top 5 per PSR sorted by score descending
    by_psr: Dict[str, List[Dict]] = defaultdict(list)
    for c in maybe_candidates:
        by_psr[c["psr_id"]].append(c)
    for psr_id in by_psr:
        by_psr[psr_id] = sorted(by_psr[psr_id], key=lambda x: x["cosine_score"], reverse=True)[:5]

    # Fetch full PSR and CAMT rows for the prompt
    with get_conn() as conn:
        psr_map = {
            r["id"]: r for r in rows_to_dicts(
                conn.execute("SELECT * FROM psr_transactions").fetchall()
            )
        }
        camt_map = {
            r["camt_id"]: r for r in rows_to_dicts(
                conn.execute("SELECT * FROM camt_transactions").fetchall()
            )
        }

    decisions = []

    for psr_id, top_candidates in by_psr.items():
        psr = psr_map.get(psr_id)
        if not psr:
            continue

        candidate_lines = []
        for i, c in enumerate(top_candidates, 1):
            camt = camt_map.get(c["camt_id"])
            if not camt:
                continue
            candidate_lines.append(
                f"  {i}. ID:{camt['camt_id']} | Dir:{camt.get('direction', '')} "
                f"| Amt:{camt.get('amount', '')} {camt.get('currency', '')} "
                f"| Date:{camt.get('booking_date', '')} "
                f"| Party:{camt.get('counterparty', '')} "
                f"| Remittance:{camt.get('remittance', '')}"
            )

        if not candidate_lines:
            continue

        prompt = (
            "You are a cash reconciliation analyst. One internal PSR payment record is unmatched.\n"
            "Review the candidate bank (CAMT) entries below and identify the best match.\n\n"
            f"PSR:\n"
            f"  ID: {psr['id']} | Direction: {psr.get('direction', '')} "
            f"| Amount: {psr.get('amount', '')} {psr.get('currency', '')}\n"
            f"  Date: {psr.get('execution_date', '')} | Reference: {psr.get('reference', '')}\n"
            f"  Invoice: {psr.get('invoice', '')} | Counterparty: {psr.get('counterparty', '')}\n\n"
            "CAMT Candidates (pre-filtered by amount/date/direction):\n"
            + "\n".join(candidate_lines)
            + "\n\nReturn valid JSON matching this schema exactly:\n"
            '{\n'
            '  "psr_id": "string",\n'
            '  "matched_camt_id": "string or null",\n'
            '  "confidence_pct": "number between 0 and 100",\n'
            '  "reason": "one sentence explaining the match or why no match exists",\n'
            '  "suggested_action": "CONFIRM_AI_MATCH or ROUTE_TO_ANALYST or NO_MATCH"\n'
            "}\n"
            "If no candidate is a credible match, set matched_camt_id to null and "
            "suggested_action to NO_MATCH."
        )

        try:
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=300,
            )
            result = json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.error("Tier 2c LLM call failed for PSR %s: %s", psr_id, exc)
            continue

        decisions.append(result)

        # Update the recon_case in DB
        if result.get("suggested_action") == "NO_MATCH":
            new_status = "Uncleared / In-Transit Payment"
            rule = "TIER2C_NO_MATCH"
        else:
            new_status = "AI-Assisted Suggested Match"
            rule = "TIER2C_LLM"

        conf = int(result.get("confidence_pct") or 0)
        reason_text = result.get("reason", "")
        matched_camt = result.get("matched_camt_id")

        with get_conn() as conn:
            conn.execute(
                """UPDATE recon_cases
                   SET reconciliation_status=?, match_confidence=?, rule_applied=?,
                       explanation=?, camt_id=COALESCE(?, camt_id),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE psr_id=?
                     AND reconciliation_status='AI - Analyst Adjudication Required'""",
                (new_status, conf, rule, reason_text, matched_camt, psr_id)
            )
            conn.commit()

    return decisions
