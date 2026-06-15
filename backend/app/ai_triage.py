"""
ai_triage.py — Pass 2 AI residual triage.

Tier 2b: deterministic pre-filter + embedding similarity (local SentenceTransformer
or OpenRouter API, toggled via EMBEDDING_PROVIDER env var).
Returns up to Top 5 candidate CAMT matches per unmatched PSR.
Tier 2c (LLM adjudication) is implemented in a separate function in this module.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from .config import settings
from .db import get_conn, json_dumps, rows_to_dicts

logger = logging.getLogger(__name__)

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


def _get_openrouter_embeddings(texts: List[str]) -> Any:
    """
    Fetch embeddings from OpenRouter in a single batch call.
    Returns an L2-normalised float32 numpy array of shape (len(texts), dim),
    so cosine similarity = dot product — identical contract to the local path.
    """
    import numpy as np
    from openai import OpenAI

    api_key = _openrouter_api_key()
    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    response = client.embeddings.create(
        model=settings.embedding_model_openrouter,
        input=texts,
        encoding_format="float",
    )
    # response.data is ordered by index
    vecs = np.array([item.embedding for item in response.data], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vecs / norms


def _openrouter_api_key() -> str:
    import os
    key = os.getenv("OPENROUTER_API_KEY", "")
    return key


def _encode(texts: List[str]) -> Any:
    """
    Encode texts to normalised embedding vectors.

    Dispatches based on EMBEDDING_PROVIDER setting:
      "openrouter" + OPENROUTER_API_KEY set  → OpenRouter batch API call
      "openrouter" + key missing             → warning, falls back to local
      "local" (default)                      → local SentenceTransformer
    """
    provider = settings.embedding_provider
    logger.info("Embedding provider configured: '%s'", provider)

    if provider == "openrouter":
        api_key = _openrouter_api_key()
        if api_key:
            logger.info(
                "Using OpenRouter embeddings: model=%s, texts=%d",
                settings.embedding_model_openrouter, len(texts),
            )
            try:
                result = _get_openrouter_embeddings(texts)
                logger.info("OpenRouter embedding succeeded: returned %d vectors", len(result))
                return result
            except Exception as exc:
                logger.error(
                    "OpenRouter embedding failed: %s: %s — check OPENROUTER_API_KEY, "
                    "model availability and account data-policy settings at "
                    "https://openrouter.ai/settings/privacy",
                    type(exc).__name__, exc,
                )
                raise
        else:
            logger.warning(
                "EMBEDDING_PROVIDER=openrouter but OPENROUTER_API_KEY is not set "
                "— falling back to local SentenceTransformer (all-MiniLM-L6-v2). "
                "Set OPENROUTER_API_KEY in .env to use online embeddings."
            )
    elif provider != "local":
        logger.warning(
            "Unknown EMBEDDING_PROVIDER='%s' — expected 'local' or 'openrouter'. "
            "Falling back to local SentenceTransformer.", provider,
        )

    logger.info("Using local SentenceTransformer (all-MiniLM-L6-v2), texts=%d", len(texts))
    return _get_model().encode(texts, normalize_embeddings=True)


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

    logger.info("Tier 2b started (unmatched_psr_ids=%s)", "all" if unmatched_psr_ids is None else len(unmatched_psr_ids))

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

    logger.info("Tier 2b pool: %d unmatched PSR, %d unmatched CAMT", len(psr_rows), len(unmatched_camt))

    if not psr_rows or not unmatched_camt:
        return []

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
        embeddings = _encode(all_texts)
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
                # Identity & financial fields — already in memory, zero extra DB cost
                "psr_amount": psr.get("amount"),
                "psr_direction": psr.get("direction"),
                "psr_reference": psr.get("reference"),
                "psr_invoice": psr.get("invoice"),
                "psr_counterparty": psr.get("counterparty"),
                "psr_currency": psr.get("currency"),
                "psr_execution_date": psr.get("execution_date"),
                "camt_amount": camt.get("amount"),
                "camt_direction": camt.get("direction"),
                "camt_booking_date": camt.get("booking_date"),
                "camt_invoice": camt.get("invoice"),
                "camt_pmt_ref": camt.get("pmt_ref"),
                "camt_counterparty": camt.get("counterparty"),
                "camt_currency": camt.get("currency"),
                "camt_remittance": camt.get("remittance"),
            })

    clear_n = sum(1 for c in candidates if c["zone"] == "clear")
    maybe_n = sum(1 for c in candidates if c["zone"] == "maybe")
    logger.info("Tier 2b done: %d candidates (%d clear, %d maybe)", len(candidates), clear_n, maybe_n)
    return candidates


def build_ai_snapshot(c: Dict, conf: int, rule: str) -> Dict:
    """
    Build a feature_snapshot dict for a Tier 2b AI triage case.
    All inputs come from the enriched candidate dict returned by run_tier2b().
    """
    psr_dir = (c.get("psr_direction") or "").upper()
    camt_dir = (c.get("camt_direction") or "").upper()
    dir_match = bool(psr_dir and camt_dir and psr_dir == camt_dir)
    try:
        psr_amt = float(c.get("psr_amount") or 0)
        camt_amt = float(c.get("camt_amount") or 0)
        amt_diff = abs(psr_amt - camt_amt)
        amt_match = amt_diff <= settings.minor_variance_tolerance
    except (TypeError, ValueError):
        psr_amt = camt_amt = amt_diff = 0.0
        amt_match = False
    cosine = c.get("cosine_score", 0.0)
    zone = c.get("zone", "maybe")
    components = [
        {"component": "Direction", "passed": dir_match, "weight": 25,
         "evidence": f"PSR: {psr_dir or '-'} | CAMT: {camt_dir or '-'}"},
        {"component": "Amount", "passed": amt_match, "weight": 30,
         "evidence": f"PSR: {psr_amt} | CAMT: {camt_amt} | \u0394{amt_diff:.2f}"},
        {"component": "Text similarity", "passed": zone == "clear", "weight": 45,
         "evidence": f"Cosine {cosine:.4f} \u2014 {zone} zone (\u22650.85=clear, 0.60\u20130.84=maybe)"},
    ]
    passed_w = sum(x["weight"] for x in components if x["passed"])
    total_w = sum(x["weight"] for x in components) or 1
    raw_score = round((passed_w / total_w) * 100, 2)
    return {
        "tier": "2b_embedding",
        "score_breakdown": {
            "rule_applied": rule,
            "engine_confidence": conf,
            "raw_component_score": raw_score,
            "components": components,
            "matched_fields": [x["component"] for x in components if x["passed"]],
            "failed_fields": [x["component"] for x in components if not x["passed"]],
            "decision_basis": f"Tier 2b embedding cosine {cosine:.4f}. Component score {raw_score}%.",
        },
    }


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

    decisions = []

    for psr_id, top_candidates in by_psr.items():
        # PSR fields are identical across all candidates for the same PSR
        first = top_candidates[0]

        candidate_lines = [
            f"  {i}. ID:{c['camt_id']} | Dir:{c.get('camt_direction', '')} "
            f"| Amt:{c.get('camt_amount', '')} {c.get('camt_currency', '')} "
            f"| Date:{c.get('camt_booking_date', '')} "
            f"| Party:{c.get('camt_counterparty', '')} "
            f"| Remittance:{c.get('camt_remittance', '')}"
            for i, c in enumerate(top_candidates, 1)
        ]

        prompt = (
            "You are a cash reconciliation analyst. One internal PSR payment record is unmatched.\n"
            "Review the candidate bank (CAMT) entries below and identify the best match.\n\n"
            f"PSR:\n"
            f"  ID: {psr_id} | Direction: {first.get('psr_direction', '')} "
            f"| Amount: {first.get('psr_amount', '')} {first.get('psr_currency', '')}\n"
            f"  Date: {first.get('psr_execution_date', '')} | Reference: {first.get('psr_reference', '')}\n"
            f"  Invoice: {first.get('psr_invoice', '')} | Counterparty: {first.get('psr_counterparty', '')}\n\n"
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

        # Build updated suggestions reflecting the LLM decision
        llm_suggestions = json_dumps([{
            "action": result.get("suggested_action", "ROUTE_TO_ANALYST"),
            "confidence": round(conf / 100.0, 4),
            "tier": "2c_llm",
            "reason": reason_text,
            "camt_id": matched_camt,
        }])

        # Build a feature snapshot with LLM-specific evidence components
        llm_action = result.get("suggested_action", "ROUTE_TO_ANALYST")
        llm_components = [
            {"component": "LLM adjudication", "passed": llm_action == "CONFIRM_AI_MATCH",
             "weight": 60, "evidence": reason_text or "LLM assessed the match."},
            {"component": "Confidence threshold", "passed": conf >= 50,
             "weight": 40, "evidence": f"LLM confidence: {conf}%"},
        ]
        passed_w = sum(x["weight"] for x in llm_components if x["passed"])
        total_w = sum(x["weight"] for x in llm_components) or 1
        llm_raw_score = round((passed_w / total_w) * 100, 2)
        llm_snapshot = json_dumps({
            "tier": "2c_llm",
            "score_breakdown": {
                "rule_applied": rule,
                "engine_confidence": conf,
                "raw_component_score": llm_raw_score,
                "components": llm_components,
                "matched_fields": [x["component"] for x in llm_components if x["passed"]],
                "failed_fields": [x["component"] for x in llm_components if not x["passed"]],
                "decision_basis": f"Tier 2c LLM: {rule}. Confidence {conf}%. {reason_text}",
            },
        })

        with get_conn() as conn:
            if result.get("suggested_action") == "NO_MATCH":
                # LLM rejected the candidate — sever the CAMT link entirely so
                # bank_amount and variance are no longer shown in the UI.
                conn.execute(
                    """UPDATE recon_cases
                       SET reconciliation_status=?, match_confidence=?, rule_applied=?,
                           explanation=?,
                           camt_id=NULL, bank_amount=NULL, variance=NULL,
                           suggestions_json=?, feature_snapshot_json=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE psr_id=?
                         AND reconciliation_status='AI - Analyst Adjudication Required'""",
                    (new_status, conf, rule, reason_text,
                     llm_suggestions, llm_snapshot, psr_id)
                )
            else:
                conn.execute(
                    """UPDATE recon_cases
                       SET reconciliation_status=?, match_confidence=?, rule_applied=?,
                           explanation=?, camt_id=COALESCE(?, camt_id),
                           suggestions_json=?, feature_snapshot_json=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE psr_id=?
                         AND reconciliation_status='AI - Analyst Adjudication Required'""",
                    (new_status, conf, rule, reason_text, matched_camt,
                     llm_suggestions, llm_snapshot, psr_id)
                )
            conn.commit()

    return decisions
