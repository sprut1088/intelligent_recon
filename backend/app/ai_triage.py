"""
ai_triage.py — Pass 2 AI residual triage.

Tier 2b: deterministic pre-filter + domain-aware candidate scoring.
  - Direction / amount / date guard rails (unchanged from previous design).
  - Surviving CAMT candidates ranked by domain signals that actually matter
    in reconciliation: counterparty fuzzy similarity (rapidfuzz), invoice
    substring match, reference substring match, counterparty-in-remittance.
  - Top 5 candidates per PSR passed to Tier 2c — no zone split, no score gate.

Tier 2c: LLM adjudication (OpenRouter / gpt-4o-mini).
  - One focused call per PSR: "which of these 5 is the match, and why?"
  - Returns CONFIRM_AI_MATCH | ROUTE_TO_ANALYST | NO_MATCH + reason sentence.
  - LLM is the sole AI decision-maker — no fast-path that bypasses reasoning.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional
from .config import settings
from .db import get_conn, json_dumps, rows_to_dicts

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain-aware candidate scoring helpers
# ---------------------------------------------------------------------------

def _counterparty_score(psr_party: str, camt_party: str) -> float:
    """rapidfuzz token_set_ratio — handles word-order swaps and legal suffixes."""
    from rapidfuzz import fuzz as rfuzz
    a = (psr_party or "").upper()
    b = (camt_party or "").upper()
    if not a or not b:
        return 0.0
    return max(rfuzz.token_set_ratio(a, b), rfuzz.WRatio(a, b)) / 100.0


def _invoice_hit(psr_invoice: str, camt_invoice: str, camt_remittance: str) -> bool:
    """True if the PSR invoice (or its numeric suffix) appears in CAMT fields."""
    inv = (psr_invoice or "").strip()
    if not inv:
        return False
    haystack = f"{camt_invoice or ''} {camt_remittance or ''}".upper()
    if inv.upper() in haystack:
        return True
    suffix = re.sub(r'^[A-Z\-]+', '', inv.upper()).strip()
    return bool(suffix) and suffix in haystack


def _reference_hit(psr_ref: str, camt_pmt_ref: str, camt_remittance: str) -> bool:
    """True if the PSR reference (or numeric suffix) appears in CAMT fields."""
    ref = (psr_ref or "").strip()
    if not ref:
        return False
    haystack = f"{camt_pmt_ref or ''} {camt_remittance or ''}".upper()
    if ref.upper() in haystack:
        return True
    suffix = re.sub(r'^[A-Z\-]+', '', ref.upper()).strip()
    return bool(suffix) and suffix in haystack


def _counterparty_in_remittance(psr_party: str, camt_remittance: str) -> bool:
    """Verbatim word-boundary match of PSR counterparty inside CAMT remittance."""
    party = (psr_party or "").strip()
    if len(party) < 4:
        return False
    remittance = (camt_remittance or "").strip()
    if not remittance:
        return False
    pattern = r'\b' + re.escape(party) + r'\b'
    return bool(re.search(pattern, remittance, re.IGNORECASE))


def _score_candidate(psr: Dict, camt: Dict) -> float:
    """
    Combined domain score 0.0-1.0 for one PSR-CAMT pair.
    Weights: counterparty fuzzy 0.40, invoice hit 0.30, reference hit 0.20,
             counterparty-in-remittance bonus 0.10.
    """
    cp = _counterparty_score(psr.get("counterparty"), camt.get("counterparty"))
    inv = _invoice_hit(psr.get("invoice"), camt.get("invoice"), camt.get("remittance"))
    ref = _reference_hit(psr.get("reference"), camt.get("pmt_ref"), camt.get("remittance"))
    rem = _counterparty_in_remittance(psr.get("counterparty"), camt.get("remittance"))
    return round(cp * 0.40 + (0.30 if inv else 0) + (0.20 if ref else 0) + (0.10 if rem else 0), 4)


# ---------------------------------------------------------------------------
# Pre-filter (unchanged)
# ---------------------------------------------------------------------------

def _passes_prefilter(psr: Dict, camt: Dict) -> bool:
    """
    Deterministic guard rails — all must pass before domain scoring runs.
    1. Direction must match (CR-CR, DR-DR).
    2. Amount difference must be within MINOR_VARIANCE_TOLERANCE.
    3. Date difference must be within IN_TRANSIT_DAYS.
    """
    psr_dir = (psr.get("direction") or "").upper()
    camt_dir = (camt.get("direction") or "").upper()
    if psr_dir and camt_dir and psr_dir != camt_dir:
        return False

    try:
        psr_amt = float(psr.get("amount") or 0)
        camt_amt = float(camt.get("amount") or 0)
        if abs(psr_amt - camt_amt) > settings.minor_variance_tolerance:
            return False
    except (TypeError, ValueError):
        return False

    try:
        from datetime import date
        psr_date = date.fromisoformat(psr.get("execution_date") or "")
        camt_date = date.fromisoformat(camt.get("booking_date") or "")
        if abs((camt_date - psr_date).days) > settings.in_transit_days:
            return False
    except (TypeError, ValueError):
        pass  # Missing/malformed dates: don't reject on date alone

    return True


# ---------------------------------------------------------------------------
# Tier 2b: find + rank candidates (replaces embedding-based run_tier2b)
# ---------------------------------------------------------------------------

def find_candidates(unmatched_psr_ids: Optional[List[str]] = None) -> List[Dict]:
    """
    For each unmatched PSR:
      1. Apply deterministic pre-filter (direction + amount + date).
      2. Score surviving CAMT entries using domain signals.
      3. Return Top 5 by score. All go to Tier 2c — no zone split.

    Returns list of enriched candidate dicts.
    """
    with get_conn() as conn:
        if unmatched_psr_ids:
            placeholders = ",".join("?" * len(unmatched_psr_ids))
            psr_rows = rows_to_dicts(conn.execute(
                f"SELECT * FROM psr_transactions WHERE id IN ({placeholders})",
                unmatched_psr_ids,
            ).fetchall())
        else:
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

    logger.info(
        "Tier 2b candidate search: %d unmatched PSR, %d available CAMT",
        len(psr_rows), len(unmatched_camt),
    )

    if not psr_rows or not unmatched_camt:
        return []

    candidates = []
    for psr in psr_rows:
        eligible = [c for c in unmatched_camt if _passes_prefilter(psr, c)]
        if not eligible:
            continue

        scored = sorted(
            [{"camt": c, "score": _score_candidate(psr, c)} for c in eligible],
            key=lambda x: x["score"],
            reverse=True,
        )[:5]

        for entry in scored:
            camt = entry["camt"]
            candidates.append({
                "psr_id": psr["id"],
                "camt_id": camt["camt_id"],
                "candidate_score": entry["score"],
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

    logger.info("Tier 2b done: %d candidates across %d PSR records", len(candidates), len(psr_rows))
    return candidates


# ---------------------------------------------------------------------------
# Tier 2b snapshot builder (for the evidence drawer)
# ---------------------------------------------------------------------------

def build_ai_snapshot(c: Dict, conf: int, rule: str) -> Dict:
    """Build a feature_snapshot dict from a candidate dict (domain-scored)."""
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

    cp_score = _counterparty_score(c.get("psr_counterparty"), c.get("camt_counterparty"))
    inv_hit = _invoice_hit(c.get("psr_invoice"), c.get("camt_invoice"), c.get("camt_remittance"))
    ref_hit = _reference_hit(c.get("psr_reference"), c.get("camt_pmt_ref"), c.get("camt_remittance"))
    rem_hit = _counterparty_in_remittance(c.get("psr_counterparty"), c.get("camt_remittance"))

    components = [
        {
            "component": "Direction",
            "passed": dir_match,
            "weight": 15,
            "evidence": f"PSR: {psr_dir or '-'} | CAMT: {camt_dir or '-'}",
        },
        {
            "component": "Amount",
            "passed": amt_match,
            "weight": 20,
            "evidence": f"PSR: {psr_amt} | CAMT: {camt_amt} | \u0394{amt_diff:.2f}",
        },
        {
            "component": "Counterparty match",
            "passed": cp_score >= 0.70,
            "weight": 30,
            "evidence": (
                f"Fuzzy score {cp_score:.2f} — "
                f"'{c.get('psr_counterparty') or '-'}' vs '{c.get('camt_counterparty') or '-'}'"
            ),
        },
        {
            "component": "Invoice match",
            "passed": inv_hit,
            "weight": 20,
            "evidence": (
                f"PSR invoice '{c.get('psr_invoice') or '-'}' "
                f"{'found' if inv_hit else 'not found'} in CAMT fields"
            ),
        },
        {
            "component": "Reference match",
            "passed": ref_hit,
            "weight": 15,
            "evidence": (
                f"PSR reference '{c.get('psr_reference') or '-'}' "
                f"{'found' if ref_hit else 'not found'} in CAMT PMT-ref/remittance"
            ),
        },
    ]
    if rem_hit:
        components.append({
            "component": "Counterparty in remittance",
            "passed": True,
            "weight": 0,
            "evidence": f"'{c.get('psr_counterparty')}' found verbatim in CAMT remittance text",
        })

    passed_w = sum(x["weight"] for x in components if x["passed"])
    total_w = sum(x["weight"] for x in components if x["weight"] > 0) or 1
    raw_score = round((passed_w / total_w) * 100, 2)

    return {
        "tier": "2b_domain",
        "score_breakdown": {
            "rule_applied": rule,
            "engine_confidence": conf,
            "raw_component_score": raw_score,
            "components": components,
            "matched_fields": [x["component"] for x in components if x["passed"]],
            "failed_fields": [x["component"] for x in components if not x["passed"]],
            "decision_basis": (
                f"Domain scoring: counterparty {cp_score:.2f}, "
                f"invoice {'hit' if inv_hit else 'miss'}, "
                f"reference {'hit' if ref_hit else 'miss'}. "
                f"Component score {raw_score}%."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Tier 2c: LLM adjudication
# ---------------------------------------------------------------------------

def run_tier2c(candidates: List[Dict]) -> List[Dict]:
    """
    LLM adjudication for all AI candidates via OpenRouter.

    Sends one call per PSR with its Top 5 CAMT candidates (ranked by domain
    score). Updates recon_cases in-place. Concurrent via ThreadPoolExecutor.
    Skips silently if OPENROUTER_API_KEY is not set.

    Returns list of LLM decision dicts.
    """
    import os
    import json
    import concurrent.futures

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — Tier 2c LLM adjudication skipped.")
        return []

    from openai import OpenAI
    from collections import defaultdict

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    # Group by PSR, keep Top 5 sorted by domain score descending
    by_psr: Dict[str, List[Dict]] = defaultdict(list)
    for c in candidates:
        by_psr[c["psr_id"]].append(c)
    for pid in by_psr:
        by_psr[pid] = sorted(by_psr[pid], key=lambda x: x["candidate_score"], reverse=True)[:5]

    decisions: List[Dict] = []

    def _process_psr(psr_id: str, top_candidates: List[Dict]) -> Optional[Dict]:
        first = top_candidates[0]

        candidate_lines = []
        for i, c in enumerate(top_candidates, 1):
            rem_hit = _counterparty_in_remittance(
                first.get("psr_counterparty"), c.get("camt_remittance")
            )
            candidate_lines.append(
                f"{i}. ID: {c['camt_id']}\n"
                f"   - Direction: {c.get('camt_direction', '')}\n"
                f"   - Amount: {c.get('camt_amount', '')} {c.get('camt_currency', '')}\n"
                f"   - Date: {c.get('camt_booking_date', '')}\n"
                f"   - Party: {c.get('camt_counterparty', '')}\n"
                f"   - Remittance: {c.get('camt_remittance', '')}\n"
                f"   - CounterpartyInRemittance: "
                f"{'YES — PSR counterparty name found verbatim in remittance' if rem_hit else 'NO'}"
            )

        system_prompt = (
            "You are an expert cash reconciliation analyst.\n"
            "Your goal is to match an internal PSR payment ledger record to the correct bank CAMT log.\n"
            "The candidate bank logs have already been pre-filtered for matching amounts, dates, and "
            "directions, and ranked by domain similarity.\n\n"
            "DECISION RULES:\n"
            "1. If 'CounterpartyInRemittance' is YES, treat it as strong evidence of a match — banks "
            "often use an intermediary name as the Party field while the actual payer appears in the "
            "remittance text.\n"
            "2. If multiple candidates are equally strong and you cannot distinguish them, do NOT guess. "
            "Set matched_camt_id to null and suggested_action to ROUTE_TO_ANALYST.\n"
            "3. CONFIDENCE THRESHOLDS:\n"
            "   - CONFIRM_AI_MATCH: Use only if confidence is >= 85%.\n"
            "   - ROUTE_TO_ANALYST: Use if confidence is 50-84%.\n"
            "   - NO_MATCH: Use if no candidate is credible (confidence < 50%).\n\n"
            "You MUST reply with valid JSON matching this schema exactly:\n"
            '{\n'
            '  "psr_id": "string",\n'
            '  "matched_camt_id": "string or null",\n'
            '  "confidence_pct": 0,\n'
            '  "reason": "One clear sentence explaining the rationale.",\n'
            '  "suggested_action": "CONFIRM_AI_MATCH|ROUTE_TO_ANALYST|NO_MATCH"\n'
            "}"
        )

        user_prompt = (
            f"Target PSR:\n"
            f"- ID: {psr_id}\n"
            f"- Amount: {first.get('psr_amount')} {first.get('psr_currency')} ({first.get('psr_direction')})\n"
            f"- Date: {first.get('psr_execution_date')}\n"
            f"- Reference: {first.get('psr_reference')}\n"
            f"- Invoice: {first.get('psr_invoice')}\n"
            f"- Counterparty: {first.get('psr_counterparty')}\n\n"
            "Top CAMT Candidates (ranked by domain score):\n"
            + "\n".join(candidate_lines)
        )

        try:
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=300,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.error("Tier 2c LLM call failed for PSR %s: %s", psr_id, exc)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_process_psr, pid, top_cands): pid
            for pid, top_cands in by_psr.items()
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                decisions.append(result)

    for result in decisions:
        psr_id_for_update = result.get("psr_id")
        if not psr_id_for_update:
            logger.warning("Tier 2c result missing psr_id, skipping: %s", result)
            continue

        action = result.get("suggested_action", "ROUTE_TO_ANALYST")
        if action == "NO_MATCH":
            new_status = "Uncleared / In-Transit Payment"
            rule = "TIER2C_NO_MATCH"
            new_reason_code = "TIER2C_NO_MATCH"
        elif action == "ROUTE_TO_ANALYST":
            new_status = "AI - Analyst Adjudication Required"
            rule = "TIER2C_LLM"
            new_reason_code = "TIER2C_ROUTE_ANALYST"
        else:  # CONFIRM_AI_MATCH
            new_status = "AI-Assisted Suggested Match"
            rule = "TIER2C_LLM"
            new_reason_code = "TIER2C_CONFIRM"

        conf = int(result.get("confidence_pct") or 0)
        reason_text = result.get("reason", "")
        matched_camt = result.get("matched_camt_id")

        llm_suggestions = json_dumps([{
            "action": action,
            "confidence": round(conf / 100.0, 4),
            "tier": "2c_llm",
            "reason": reason_text,
            "camt_id": matched_camt,
        }])

        llm_components = [
            {
                "component": "LLM adjudication",
                "passed": action == "CONFIRM_AI_MATCH",
                "weight": 60,
                "evidence": reason_text or "LLM assessed the match.",
            },
            {
                "component": "Confidence threshold",
                "passed": conf >= 50,
                "weight": 40,
                "evidence": f"LLM confidence: {conf}%",
            },
        ]
        passed_w = sum(x["weight"] for x in llm_components if x["passed"])
        total_w = sum(x["weight"] for x in llm_components) or 1
        llm_snapshot = json_dumps({
            "tier": "2c_llm",
            "score_breakdown": {
                "rule_applied": rule,
                "engine_confidence": conf,
                "raw_component_score": round((passed_w / total_w) * 100, 2),
                "components": llm_components,
                "matched_fields": [x["component"] for x in llm_components if x["passed"]],
                "failed_fields": [x["component"] for x in llm_components if not x["passed"]],
                "decision_basis": f"Tier 2c LLM: {rule}. Confidence {conf}%. {reason_text}",
            },
        })

        with get_conn() as conn:
            if action == "NO_MATCH":
                conn.execute(
                    """UPDATE recon_cases
                       SET reconciliation_status=?, reason_code=?, match_confidence=?,
                           rule_applied=?, explanation=?,
                           camt_id=NULL, bank_amount=NULL, variance=NULL,
                           suggestions_json=?, feature_snapshot_json=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE psr_id=?
                         AND reconciliation_status='AI - Analyst Adjudication Required'""",
                    (new_status, new_reason_code, conf, rule, reason_text,
                     llm_suggestions, llm_snapshot, psr_id_for_update),
                )
            else:
                conn.execute(
                    """UPDATE recon_cases
                       SET reconciliation_status=?, reason_code=?, match_confidence=?,
                           rule_applied=?, explanation=?, camt_id=COALESCE(?, camt_id),
                           suggestions_json=?, feature_snapshot_json=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE psr_id=?
                         AND reconciliation_status='AI - Analyst Adjudication Required'""",
                    (new_status, new_reason_code, conf, rule, reason_text,
                     matched_camt, llm_suggestions, llm_snapshot, psr_id_for_update),
                )
            conn.commit()

    return decisions
