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

from .db import get_conn, get_meta, json_dumps, rows_to_dicts



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

    2. Amount difference must be within ai_candidate_variance_pct of the larger amount.

    3. Date difference must be within IN_TRANSIT_DAYS.

    """

    psr_dir = (psr.get("direction") or "").upper()

    camt_dir = (camt.get("direction") or "").upper()

    if psr_dir and camt_dir and psr_dir != camt_dir:

        return False



    try:

        psr_amt = float(psr.get("amount") or 0)

        camt_amt = float(camt.get("amount") or 0)

        max_amt = max(abs(psr_amt), abs(camt_amt), 1)

        if abs(psr_amt - camt_amt) / max_amt > settings.ai_candidate_variance_pct:

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

                      OR reconciliation_status LIKE '%Uncleared%'

                      OR reconciliation_status LIKE 'AI%'"""

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

    Skips silently if neither OPENROUTER_API_KEY nor ANTHROPIC_API_KEY is set

    (depending on LLM_PROVIDER setting).



    Returns list of LLM decision dicts.

    """

    import os

    import json

    import concurrent.futures

    from .config import settings



    provider = settings.llm_provider  # "openrouter" or "anthropic"

    model    = settings.llm_model

    max_tok  = settings.llm_max_tokens



    if provider == "anthropic":

        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:

            logger.warning("ANTHROPIC_API_KEY not set — Tier 2c LLM adjudication skipped.")

            return []

        import anthropic as _anthropic

        _anthropic_client = _anthropic.Anthropic(api_key=api_key)

        _openai_client = None

    else:  # openrouter (default)

        api_key = os.getenv("OPENROUTER_API_KEY")

        if not api_key:

            logger.warning("OPENROUTER_API_KEY not set — Tier 2c LLM adjudication skipped.")

            return []

        from openai import OpenAI

        _openai_client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

        _anthropic_client = None



    from collections import defaultdict



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

            "You are a cash reconciliation engine. Be precise and terse.\n\n"

            "CONTEXT: Every candidate already passed amount (within tolerance), date (within "

            "in-transit window), and direction checks. Do NOT re-examine those — focus solely "

            "on IDENTITY signals to pick the right candidate.\n\n"

            "IDENTITY SIGNALS (in priority order):\n"

            "1. Counterparty name — word-order swaps ('Pinnacle Group' = 'Group Pinnacle'), "

            "legal suffix differences ('Corp' = 'Corp Ltd'), and abbreviations all count as MATCH.\n"

            "2. Invoice number in remittance text — strong positive evidence.\n"

            "3. Reference number in remittance text — strong positive evidence.\n"

            "4. CounterpartyInRemittance=YES — bank used intermediary as Party; actual payer "

            "is in remittance text; treat as strong positive.\n"

            "5. Generic remittance text (e.g. 'Technology Services Payment') — NOT evidence "

            "for or against; ignore it.\n\n"

            "DECISION RULES:\n"

            "- CONFIRM_AI_MATCH (>=85%): counterparty is clearly the same entity (fuzzy name "

            "match or exact), OR invoice/reference found in remittance, AND no other candidate "

            "is equally strong.\n"

            "- ROUTE_TO_ANALYST (30-84%): some identity overlap but not conclusive, OR two "

            "candidates are indistinguishable — pick the best fit, set it as matched_camt_id, "

            "and flag for human review.\n"

            "- NO_MATCH (<30%): zero identity field overlap across ALL candidates. "

            "Should be rare given pre-filtering. Set matched_camt_id to null.\n\n"

            "REASON FIELD: One short factual sentence. State WHAT matched or WHY it is "

            "ambiguous. No filler phrases. Max 20 words.\n\n"

            "Reply with RAW JSON only. Do not use markdown blocks:\n"

            '{"psr_id":"string","matched_camt_id":"string or null",'

            '"confidence_pct":"integer 0-100","reason":"string","suggested_action":"CONFIRM_AI_MATCH|ROUTE_TO_ANALYST|NO_MATCH",'

            '"candidate_scores":[{"camt_id":"string","confidence_pct":"integer 0-100"}]}'

            " — candidate_scores must include one entry per candidate with your identity-match confidence for each."

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

            if provider == "anthropic":

                response = _anthropic_client.messages.create(

                    model=model,

                    system=system_prompt,

                    messages=[{"role": "user", "content": user_prompt}],

                    max_tokens=max_tok,

                )

                raw_content = response.content[0].text

            else:

                response = _openai_client.chat.completions.create(

                    model=model,

                    messages=[

                        {"role": "system", "content": system_prompt},

                        {"role": "user", "content": user_prompt},

                    ],

                    response_format={"type": "json_object"},

                    temperature=0,

                    max_tokens=max_tok,

                )

                raw_content = response.choices[0].message.content

            result = json.loads(raw_content)

            result["_candidates"] = top_candidates[:5]

            return result

        except json.JSONDecodeError:

            # Strip markdown fences if the model wraps output despite instructions

            raw = raw_content.strip()

            raw = re.sub(r'^```(?:json)?\s*', '', raw)

            raw = re.sub(r'\s*```$', '', raw)

            try:

                result = json.loads(raw)

                result["_candidates"] = top_candidates[:5]

                return result

            except Exception:

                logger.error("Tier 2c JSON parse failed for PSR %s after strip", psr_id)

                return None

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

            new_status = "AI Confirmed — No Match"

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

        per_cand_scores = {

            s["camt_id"]: s.get("confidence_pct")

            for s in result.get("candidate_scores") or []

            if s.get("camt_id")

        }

        candidates_reviewed = [

            {

                "camt_id": c.get("camt_id"),

                "counterparty": c.get("camt_counterparty") or "",

                "amount": c.get("camt_amount"),

                "currency": c.get("camt_currency") or "",

                "date": c.get("camt_booking_date") or "",

                "pmt_ref": c.get("camt_pmt_ref") or "",

                "invoice": c.get("camt_invoice") or "",

                "remittance": c.get("camt_remittance") or "",

                "domain_score": c.get("candidate_score"),

                "llm_confidence": per_cand_scores.get(c.get("camt_id")),

            }

            for c in result.get("_candidates", [])

        ]

        passed_w = sum(x["weight"] for x in llm_components if x["passed"])

        total_w = sum(x["weight"] for x in llm_components) or 1

        llm_snapshot = json_dumps({

            "tier": "2c_llm",

            "candidates_reviewed": candidates_reviewed,

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





# ---------------------------------------------------------------------------

# AI Verifier — second-opinion pass for static-rule exception cases

# ---------------------------------------------------------------------------



def verify_exception_cases(case_ids: Optional[List[str]] = None) -> List[Dict]:

    """

    AI second-opinion pass for exception cases produced by static rules.



    For each case the LLM reviews the already-proposed PSR<->CAMT pair and

    returns AGREE / CAUTION / DISAGREE.  Result is merged into the existing

    feature_snapshot_json under 'ai_verification'. reconciliation_status is

    NOT changed — this is an annotation only.

    """

    import os

    import json

    import time

    import concurrent.futures

    from datetime import datetime



    VERIFIABLE_STATUSES = [

        "Suggested Match - Analyst Review",

        "Exception - Amount Variance Review",

    ]



    provider = settings.llm_provider

    model    = settings.llm_model

    max_tok  = settings.llm_max_tokens

    started_at = time.monotonic()



    logger.info(

        "AI verifier starting | provider=%s model=%s max_tokens=%s target_statuses=%s case_ids=%s",

        provider, model, max_tok, VERIFIABLE_STATUSES,

        (case_ids if case_ids else "<auto>"),

    )



    if provider == "anthropic":

        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:

            logger.warning("AI verifier skipped — ANTHROPIC_API_KEY not set.")

            return []

        import anthropic as _anthropic

        _anthropic_client = _anthropic.Anthropic(api_key=api_key)

        _openai_client = None

    else:

        api_key = os.getenv("OPENROUTER_API_KEY")

        if not api_key:

            logger.warning("AI verifier skipped — OPENROUTER_API_KEY not set.")

            return []

        from openai import OpenAI

        _openai_client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

        _anthropic_client = None



    with get_conn() as conn:

        if case_ids:

            placeholders = ",".join("?" * len(case_ids))

            rows = rows_to_dicts(conn.execute(

                f"SELECT * FROM recon_cases WHERE case_id IN ({placeholders})",

                case_ids,

            ).fetchall())

            logger.info("AI verifier: %d cases requested by ID", len(rows))

        else:

            status_ph = ",".join("?" * len(VERIFIABLE_STATUSES))

            rows = rows_to_dicts(conn.execute(

                f"""SELECT * FROM recon_cases

                    WHERE reconciliation_status IN ({status_ph})

                      AND psr_id IS NOT NULL AND psr_id != ''

                      AND camt_id IS NOT NULL AND camt_id != ''""",

                VERIFIABLE_STATUSES,

            ).fetchall())

            by_status = {}

            for r in rows:

                s = r["reconciliation_status"]

                by_status[s] = by_status.get(s, 0) + 1

            logger.info("AI verifier: found %d eligible cases — %s", len(rows), by_status)



    if not rows:

        logger.info("AI verifier: no eligible cases found — nothing to do.")

        return []



    # Enrich each row with CAMT fields from camt_transactions (not stored in recon_cases).

    # Mirror the same lookup logic used in main.py get_case().

    with get_conn() as conn:

        for row in rows:

            camt_id = row.get("camt_id")

            if camt_id:

                match_key = row.get("match_key", "")

                camt_row = conn.execute(

                    "SELECT counterparty, pmt_ref, invoice, remittance FROM camt_transactions WHERE ntry_id = ?",

                    (match_key,),

                ).fetchone()

                if not camt_row:

                    camt_row = conn.execute(

                        "SELECT counterparty, pmt_ref, invoice, remittance FROM camt_transactions WHERE camt_id = ?",

                        (camt_id,),

                    ).fetchone()

                if camt_row:

                    row["camt_counterparty"] = camt_row["counterparty"]

                    row["camt_pmt_ref"]      = camt_row["pmt_ref"]

                    row["camt_invoice"]      = camt_row["invoice"]

                    row["camt_remittance"]   = camt_row["remittance"]

                    logger.debug(

                        "AI verifier: enriched %s with CAMT data — counterparty=%r pmt_ref=%r invoice=%r remittance=%r",

                        row.get("case_id"), camt_row["counterparty"], camt_row["pmt_ref"],

                        camt_row["invoice"], camt_row["remittance"],

                    )

                else:

                    logger.warning(

                        "AI verifier: no camt_transactions row found for case %s (camt_id=%s match_key=%s)",

                        row.get("case_id"), camt_id, match_key,

                    )



    system_prompt = (

        "You are a cash reconciliation auditor. A deterministic rule has proposed a match "

        "between a PSR payment record and a bank CAMT entry.\n"

        "Your job: review the IDENTITY signals and give a second opinion.\n"

        "Focus on whether these two records describe the same real-world payment.\n"

        "Identity signals: counterparty name, payment reference, invoice number, remittance text.\n"

        "Note: counterparty names may differ by legal suffix (Ltd, plc, GmbH) — treat those as matching.\n\n"

        "Return raw JSON only — no markdown:\n"

        '{"verdict":"AGREE|CAUTION|DISAGREE","confidence_pct":0-100,"note":"string"}\n'

        "- AGREE: identity signals clearly support the match\n"

        "- CAUTION: some overlap but signals are ambiguous or mixed\n"

        "- DISAGREE: identity signals suggest these are different payments\n"

        "Max 20 words in note."

    )



    results: List[Dict] = []



    def _verify_case(case: Dict) -> Optional[Dict]:

        case_id = case["case_id"]

        logger.info(

            "AI verifier: processing %s | status=%s rule=%s psr=%s camt=%s",

            case_id, case.get("reconciliation_status"), case.get("rule_applied"),

            case.get("psr_id"), case.get("camt_id"),

        )

        user_prompt = (

            f"Rule applied: {case.get('rule_applied', '')} "

            f"(confidence {case.get('match_confidence', '')}%)\n\n"

            f"PSR:\n"

            f"- ID: {case.get('psr_id', '')}\n"

            f"- Reference: {case.get('reference', '') or ''}\n"

            f"- Invoice: {case.get('invoice', '') or ''}\n"

            f"- Counterparty: {case.get('counterparty', '') or ''}\n\n"

            f"CAMT:\n"

            f"- ID: {case.get('camt_id', '')}\n"

            f"- PMT Reference: {case.get('camt_pmt_ref', '') or ''}\n"

            f"- Invoice: {case.get('camt_invoice', '') or ''}\n"

            f"- Counterparty: {case.get('camt_counterparty', '') or ''}\n"

            f"- Remittance: {case.get('camt_remittance', '') or ''}"

        )

        try:

            if provider == "anthropic":

                response = _anthropic_client.messages.create(

                    model=model, system=system_prompt,

                    messages=[{"role": "user", "content": user_prompt}],

                    max_tokens=max_tok,

                )

                raw = response.content[0].text

            else:

                response = _openai_client.chat.completions.create(

                    model=model,

                    messages=[

                        {"role": "system", "content": system_prompt},

                        {"role": "user", "content": user_prompt},

                    ],

                    response_format={"type": "json_object"},

                    temperature=0, max_tokens=max_tok,

                )

                raw = response.choices[0].message.content



            # Strip markdown fences — Anthropic often wraps despite instructions

            raw = raw.strip()

            raw = re.sub(r'^```(?:json)?\s*', '', raw)

            raw = re.sub(r'\s*```$', '', raw).strip()

            logger.debug("AI verifier: %s raw response: %s", case_id, raw[:200])



            try:

                result = json.loads(raw)

            except json.JSONDecodeError as e:

                logger.error(

                    "AI verifier: %s JSON parse failed — %s | raw=%r",

                    case_id, e, raw[:300],

                )

                return None



            verdict = result.get("verdict", "CAUTION")

            if verdict not in ("AGREE", "CAUTION", "DISAGREE"):

                verdict = "CAUTION"



            annotation = {

                "verdict": verdict,

                "confidence_pct": result.get("confidence_pct"),

                "note": result.get("note", ""),

                "verified_at": datetime.utcnow().isoformat(),

            }



            with get_conn() as conn:

                existing_row = conn.execute(

                    "SELECT feature_snapshot_json FROM recon_cases WHERE case_id = ?",

                    (case["case_id"],),

                ).fetchone()

                snapshot = json.loads(existing_row["feature_snapshot_json"] or "{}") if existing_row else {}

                snapshot["ai_verification"] = annotation

                conn.execute(

                    "UPDATE recon_cases SET feature_snapshot_json = ?, updated_at = CURRENT_TIMESTAMP WHERE case_id = ?",

                    (json_dumps(snapshot), case["case_id"]),

                )

                conn.commit()



            logger.info(

                "AI verifier: %s -> verdict=%s confidence=%s%% note=%r",

                case_id, verdict, result.get("confidence_pct"), result.get("note", ""),

            )

            return {"case_id": case_id, **annotation}



        except Exception as exc:

            logger.error("AI verifier: FAILED for %s (%s: %s)", case_id, type(exc).__name__, exc)

            return None



    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:

        futures = {executor.submit(_verify_case, row): row for row in rows}

        for future in concurrent.futures.as_completed(futures):

            res = future.result()

            if res:

                results.append(res)



    elapsed = time.monotonic() - started_at

    verdict_counts = {"AGREE": 0, "CAUTION": 0, "DISAGREE": 0}

    for r in results:

        v = r.get("verdict")

        if v in verdict_counts:

            verdict_counts[v] += 1

    failed = len(rows) - len(results)

    logger.info(

        "AI verifier complete: annotated=%d/%d failed=%d verdicts=%s elapsed=%.2fs",

        len(results), len(rows), failed, verdict_counts, elapsed,

    )

    return results





# ---------------------------------------------------------------------------

# Trade exception AI verification

# ---------------------------------------------------------------------------



TRADE_EXCEPTION_STATUSES = [

    "Exception - Price Variance",

    "Exception - Quantity Mismatch",

    "Exception - Unmatched Trade",

    "Exception - Unmatched Custodian Record",

]



TRADE_SYSTEM_PROMPT = (

    "You are a trade operations AI analyst. You are reviewing exception cases from an "

    "automated trade reconciliation engine that matches Front Office FIX execution reports "

    "against Custodian settlement confirmations (CCF).\n\n"

    "For each case you receive:\n"

    "- The exception type and rule that triggered it\n"

    "- Front Office fields (order ref, ISIN, side, quantity, price)\n"

    "- Custodian fields (clearing ref, ISIN, side, quantity, price)\n"

    "- The computed variance\n\n"

    "Your job: provide an intelligent diagnosis and recommended action.\n\n"

    "Return raw JSON only — no markdown:\n"

    '{"verdict":"AGREE|CAUTION|DISAGREE",'

    '"confidence_pct":0-100,'

    '"diagnosis":"string",'

    '"root_cause":"string",'

    '"recommended_action":"string",'

    '"routing_desk":"string"}\n\n'

    "Verdict meanings:\n"

    "- AGREE: The exception is explainable and can be resolved (e.g. minor rounding, known fee, data entry error)\n"

    "- CAUTION: Likely explainable but needs analyst confirmation (e.g. transposition error, partial fill, timing)\n"

    "- DISAGREE: Serious unexplained break requiring immediate attention (e.g. missing settlement, unknown counterparty)\n\n"

    "Guidelines:\n"

    "- Price differences < $1 on otherwise perfect matches ? likely regulatory fee ? AGREE\n"

    "- Price differences that look like digit transpositions (e.g. 174.95 vs 164.95) ? keyboard error ? CAUTION\n"

    "- Quantity mismatches with matching ISIN/price ? partial allocation or late fill ? CAUTION\n"

    "- Orphan trades near batch cutoff times ? predict next-day settlement ? CAUTION\n"

    "- Orphan custodian records with no reference ? unsolicited ? DISAGREE\n"

    "Max 25 words each for diagnosis, root_cause, and recommended_action."

)









TRADE_FUZZY_SYSTEM_PROMPT = (

    "You are a trade operations specialist. The automated reconciliation engine has matched "

    "exact ExecutionIDs (FIX Tag 17 <-> CCF Execution ID). These records remain unmatched and "

    "may have minor data discrepancies.\n\n"

    "Each record includes both exec_id (primary identifier) and order_id (secondary evidence).\n"

    "Your task: identify which Unmatched FIX executions pair with which Unmatched CCF custodian "

    "records. Consider:\n"

    "- exec_id or order_id differing by punctuation, whitespace, case, truncation, or 1-2 character errors\n"

    "- Quantities within \u00b11 share\n"

    "- Prices within \u00b1$0.01\n"

    "- Split fills: one FIX matched to multiple CCFs whose quantities sum to the FIX quantity\n\n"

    "Return raw JSON only \u2014 no markdown, no explanation outside the JSON. "

    "fix_exec_id and ccf_refs must use the exec_id values (not order_id):\n"

    '{"matches": [{"fix_exec_id": "...", "ccf_refs": ["..."], "confidence_pct": 0-100, '

    '"match_type": "1_TO_1|1_TO_N", "reason": "..."}]}\n\n'

    "Return {\"matches\": []} if no matches found. Only include matches with confidence \u226570%.\n"

    "Max 20 words for reason."

)





def verify_trade_exceptions(case_ids: Optional[List[str]] = None) -> List[Dict]:

    """AI pass for trade recon.



    Phase A: sends all orphan FIX + CCF records to the LLM to identify fuzzy matches.

    Phase B: LLM diagnosis of remaining deterministic exceptions (T2/T3 breaks).

    """

    import os
    import sys

    import json

    import concurrent.futures

    from datetime import datetime



    provider = settings.llm_provider

    model = settings.llm_model

    max_tok = settings.llm_max_tokens



    print(f"[TRADE AI] verify_trade_exceptions called | provider={provider!r} model={model!r}", flush=True, file=sys.stderr)

    logger.info("Trade AI verifier starting | provider=%s model=%s", provider, model)



    if provider == "anthropic":

        api_key = os.getenv("ANTHROPIC_API_KEY")

        print(f"[TRADE AI] ANTHROPIC_API_KEY present={bool(api_key)}", flush=True, file=sys.stderr)

        if not api_key:

            logger.warning("Trade AI verifier skipped — ANTHROPIC_API_KEY not set.")

            return []

        import anthropic as _anthropic

        _anthropic_client = _anthropic.Anthropic(api_key=api_key)

        _openai_client = None

    else:

        api_key = os.getenv("OPENROUTER_API_KEY")

        print(f"[TRADE AI] OPENROUTER_API_KEY present={bool(api_key)}", flush=True, file=sys.stderr)

        if not api_key:

            logger.warning("Trade AI verifier skipped — OPENROUTER_API_KEY not set.")

            return []

        from openai import OpenAI

        _openai_client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

        _anthropic_client = None



    # --- Phase A: LLM fuzzy matching for orphan trade records ---

    phase_a_results: List[Dict] = []

    with get_conn() as conn:

        _fz_batch_id   = get_meta(conn, "active_batch_id")

        _fz_recon_type = get_meta(conn, "recon_type", "")

        _fz_orphan_fix = rows_to_dicts(conn.execute(

            "SELECT case_id, psr_id FROM recon_cases "

            "WHERE case_id LIKE 'TCASE-%' AND rule_applied='T4_ORPHAN_TRADE'"

        ).fetchall())

        _fz_orphan_ccf = rows_to_dicts(conn.execute(

            "SELECT case_id, camt_id FROM recon_cases "

            "WHERE case_id LIKE 'TCASE-%' AND rule_applied='T5_ORPHAN_CUSTODIAN'"

        ).fetchall())



    logger.info(

        "Trade AI fuzzy | recon_type=%r batch_id=%r orphan_fix=%d orphan_ccf=%d",

        _fz_recon_type, _fz_batch_id, len(_fz_orphan_fix), len(_fz_orphan_ccf),

    )

    print(f"[TRADE AI FUZZY] recon_type={_fz_recon_type!r} batch_id={_fz_batch_id!r} "

          f"orphan_fix={len(_fz_orphan_fix)} orphan_ccf={len(_fz_orphan_ccf)}", flush=True, file=sys.stderr)



    _fz_fix_path = _fz_ccf_path = None

    if _fz_recon_type == "TRADE" and _fz_batch_id:

        try:

            from .ingestion import _trade_batch_file_paths

            _fz_fix_path, _fz_ccf_path = _trade_batch_file_paths(_fz_batch_id)

        except Exception as _e:

            logger.warning("Trade AI fuzzy phase: could not resolve file paths — %s", _e)



    if (

        _fz_recon_type == "TRADE"

        and _fz_fix_path and _fz_ccf_path

        and _fz_orphan_fix and _fz_orphan_ccf

    ):

        from .parsers import parse_fix_file, parse_ccf_file



        _fix_by_id      = {f.exec_id: f for f in parse_fix_file(_fz_fix_path) if f.exec_id}

        _ccf_by_exec_id = {c.exec_id: c for c in parse_ccf_file(_fz_ccf_path) if c.exec_id}

        logger.info(

            "Trade AI fuzzy | parsed files: fix_records=%d ccf_records=%d",

            len(_fix_by_id), len(_ccf_by_ref),

        )

        print(f"[TRADE AI FUZZY] parsed files: fix_records={len(_fix_by_id)} ccf_records={len(_ccf_by_ref)}", flush=True, file=sys.stderr)



        # Payload identifiers: exec_id (FIX Tag 17 / CCF exec block) is the matching key;
        # order_id (FIX Tag 37 / CCF clearing_ref) is exposed for LLM evidence only.
        fix_payload = [

            {"exec_id": r["psr_id"],
             "order_id": _fix_by_id[r["psr_id"]].trade_id,
             "isin": _fix_by_id[r["psr_id"]].isin,
             "side": _fix_by_id[r["psr_id"]].side,
             "quantity": _fix_by_id[r["psr_id"]].quantity,
             "price": _fix_by_id[r["psr_id"]].price}

            for r in _fz_orphan_fix if r["psr_id"] in _fix_by_id

        ]

        ccf_payload = [

            {"exec_id": r["camt_id"],
             "order_id": _ccf_by_exec_id[r["camt_id"]].clearing_ref,
             "isin": _ccf_by_exec_id[r["camt_id"]].isin,
             "side": _ccf_by_exec_id[r["camt_id"]].side,
             "quantity": _ccf_by_exec_id[r["camt_id"]].quantity,
             "price": _ccf_by_exec_id[r["camt_id"]].price}

            for r in _fz_orphan_ccf if r["camt_id"] in _ccf_by_exec_id

        ]



        if fix_payload and ccf_payload:

            logger.info(

                "Trade AI fuzzy | sending to LLM: fix_payload=%d ccf_payload=%d",

                len(fix_payload), len(ccf_payload),

            )

            logger.debug("Trade AI fuzzy | FIX payload: %s", json.dumps(fix_payload))

            logger.debug("Trade AI fuzzy | CCF payload: %s", json.dumps(ccf_payload))

            print(f"[TRADE AI FUZZY] sending to LLM — fix={len(fix_payload)} ccf={len(ccf_payload)}", flush=True, file=sys.stderr)

            print(f"[TRADE AI FUZZY] FIX payload: {json.dumps(fix_payload)}", flush=True, file=sys.stderr)

            print(f"[TRADE AI FUZZY] CCF payload: {json.dumps(ccf_payload)}", flush=True, file=sys.stderr)

            _fz_user_msg = (

                f"UNMATCHED FIX EXECUTIONS:\n{json.dumps(fix_payload, indent=2)}\n\n"

                f"UNMATCHED CCF RECORDS:\n{json.dumps(ccf_payload, indent=2)}"

            )

            try:

                if provider == "anthropic":

                    _fz_resp = _anthropic_client.messages.create(

                        model=model, system=TRADE_FUZZY_SYSTEM_PROMPT,

                        messages=[{"role": "user", "content": _fz_user_msg}],

                        max_tokens=max_tok,

                    )

                    _fz_raw = _fz_resp.content[0].text

                else:

                    _fz_resp = _openai_client.chat.completions.create(

                        model=model,

                        messages=[

                            {"role": "system", "content": TRADE_FUZZY_SYSTEM_PROMPT},

                            {"role": "user", "content": _fz_user_msg},

                        ],

                        response_format={"type": "json_object"},

                        temperature=0, max_tokens=max_tok,

                    )

                    _fz_raw = _fz_resp.choices[0].message.content



                _fz_raw = re.sub(r'^```(?:json)?\s*', '', _fz_raw.strip())

                _fz_raw = re.sub(r'\s*```$', '', _fz_raw).strip()

                logger.info("Trade AI fuzzy | LLM raw response: %s", _fz_raw)

                print(f"[TRADE AI FUZZY] LLM raw response: {_fz_raw}", flush=True, file=sys.stderr)

                _fz_matches = json.loads(_fz_raw).get("matches", [])

                logger.info("Trade AI fuzzy | LLM returned %d match(es)", len(_fz_matches))

                print(f"[TRADE AI FUZZY] LLM returned {len(_fz_matches)} match(es): {_fz_matches}", flush=True, file=sys.stderr)

                _now = datetime.utcnow().isoformat()

                _fix_case_map = {r["psr_id"]: r["case_id"] for r in _fz_orphan_fix if r["psr_id"]}

                _ccf_case_map = {r["camt_id"]: r["case_id"] for r in _fz_orphan_ccf if r["camt_id"]}



                with get_conn() as conn:

                    for _m in _fz_matches:

                        _exec_id  = _m.get("fix_exec_id", "")

                        _ccf_refs = _m.get("ccf_refs", [])

                        _conf     = int(_m.get("confidence_pct", 0))

                        _reason   = _m.get("reason", "")

                        _mtype    = _m.get("match_type", "1_TO_1")

                        if _conf < 70 or not _exec_id or not _ccf_refs:

                            logger.info(

                                "Trade AI fuzzy | skipped match exec_id=%r ccf_refs=%r conf=%d",

                                _exec_id, _ccf_refs, _conf,

                            )

                            print(f"[TRADE AI FUZZY] skipped: exec_id={_exec_id!r} ccf_refs={_ccf_refs!r} conf={_conf}", flush=True, file=sys.stderr)

                            continue



                        _ai_ann = {"matched_to": _ccf_refs, "match_type": _mtype,

                                   "confidence_pct": _conf, "reason": _reason, "matched_at": _now}



                        _fix_cid = _fix_case_map.get(_exec_id)

                        if _fix_cid:

                            _snap_row = conn.execute(

                                "SELECT feature_snapshot_json FROM recon_cases WHERE case_id=?",

                                (_fix_cid,),

                            ).fetchone()

                            _snap = json.loads((_snap_row["feature_snapshot_json"] or "{}") if _snap_row else "{}")

                            _snap["ai_match"] = _ai_ann

                            conn.execute(

                                "UPDATE recon_cases SET reconciliation_status='AI Suggested Match', "

                                "match_confidence=?, feature_snapshot_json=?, "

                                "updated_at=CURRENT_TIMESTAMP WHERE case_id=?",

                                (_conf, json_dumps(_snap), _fix_cid),

                            )

                            phase_a_results.append({"case_id": _fix_cid, "ai_match": _ai_ann})



                        for _ref in _ccf_refs:

                            _ccf_cid = _ccf_case_map.get(_ref)

                            if _ccf_cid:

                                _snap_row = conn.execute(

                                    "SELECT feature_snapshot_json FROM recon_cases WHERE case_id=?",

                                    (_ccf_cid,),

                                ).fetchone()

                                _snap = json.loads((_snap_row["feature_snapshot_json"] or "{}") if _snap_row else "{}")

                                _snap["ai_match"] = {**_ai_ann, "matched_to": [_exec_id]}

                                conn.execute(

                                    "UPDATE recon_cases SET reconciliation_status='AI Suggested Match', "

                                    "match_confidence=?, feature_snapshot_json=?, "

                                    "updated_at=CURRENT_TIMESTAMP WHERE case_id=?",

                                    (_conf, json_dumps(_snap), _ccf_cid),

                                )

                    conn.commit()



                logger.info("Trade AI fuzzy phase: %d matches applied from LLM", len(_fz_matches))

                print(f"[TRADE AI FUZZY] phase complete: {len(_fz_matches)} matches applied", flush=True, file=sys.stderr)

            except Exception as _fz_exc:

                logger.exception("Trade AI fuzzy phase failed: %s", _fz_exc)

                print(f"[TRADE AI FUZZY] EXCEPTION: {_fz_exc}", flush=True, file=sys.stderr)

        else:

            logger.warning(

                "Trade AI fuzzy | skipped LLM call — fix_payload=%d ccf_payload=%d",

                len(fix_payload), len(ccf_payload),

            )

            print(f"[TRADE AI FUZZY] skipped LLM — fix_payload={len(fix_payload)} ccf_payload={len(ccf_payload)}", flush=True, file=sys.stderr)

    else:

        logger.info(

            "Trade AI fuzzy | conditions not met — recon_type=%r fix_path=%r ccf_path=%r "

            "orphan_fix=%d orphan_ccf=%d",

            _fz_recon_type, _fz_fix_path, _fz_ccf_path,

            len(_fz_orphan_fix), len(_fz_orphan_ccf),

        )

        print(f"[TRADE AI FUZZY] conditions not met — recon_type={_fz_recon_type!r} "

              f"fix_path={_fz_fix_path!r} ccf_path={_fz_ccf_path!r} "

              f"orphan_fix={len(_fz_orphan_fix)} orphan_ccf={len(_fz_orphan_ccf)}", flush=True, file=sys.stderr)



    # --- Phase B: LLM diagnosis of remaining deterministic exceptions ---

    with get_conn() as conn:

        if case_ids:

            placeholders = ",".join("?" * len(case_ids))

            rows = rows_to_dicts(conn.execute(

                f"SELECT * FROM recon_cases WHERE case_id IN ({placeholders})",

                case_ids,

            ).fetchall())

        else:

            status_ph = ",".join("?" * len(TRADE_EXCEPTION_STATUSES))

            rows = rows_to_dicts(conn.execute(

                f"""SELECT * FROM recon_cases

                    WHERE case_id LIKE 'TCASE-%'

                      AND reconciliation_status IN ({status_ph})

                      AND (feature_snapshot_json NOT LIKE '%ai_verification%'

                           OR feature_snapshot_json IS NULL)""",

                TRADE_EXCEPTION_STATUSES,

            ).fetchall())



    if not rows:

        logger.info("Trade AI verifier: no eligible cases — nothing to do.")

        return phase_a_results



    logger.info("Trade AI verifier: %d exception cases to process", len(rows))

    results: List[Dict] = []



    def _build_trade_prompt(case: Dict) -> str:

        snap = json.loads(case.get("feature_snapshot_json") or "{}")

        return (

            f"Exception Type: {case.get('reconciliation_status', '')}\n"

            f"Rule Applied: {case.get('rule_applied', '')} "

            f"(engine confidence: {case.get('match_confidence', '')}%)\n\n"

            f"Front Office (FIX):\n"

            f"- Order Reference: {case.get('reference', '') or 'N/A'}\n"

            f"- ISIN: {snap.get('isin_match', 'unknown')} (matched={snap.get('isin_match', False)})\n"

            f"- Side: {snap.get('side', 'N/A')}\n"

            f"- Quantity: {case.get('internal_amount', 'N/A')}\n"

            f"- Price: {snap.get('price_variance', 'N/A')} variance\n\n"

            f"Custodian (CCF):\n"

            f"- Clearing Reference: {case.get('camt_id', '') or 'N/A'}\n"

            f"- Execution ID: {case.get('counterparty', '') or 'N/A'}\n"

            f"- Quantity: {case.get('bank_amount', 'N/A')}\n\n"

            f"Variance: {case.get('variance', 'N/A')}\n"

            f"Quantity Match: {snap.get('quantity_match', 'N/A')}\n"

            f"Quantity Variance: {snap.get('quantity_variance', 'N/A')}\n"

            f"Price Match: {snap.get('price_match', 'N/A')}\n"

            f"Price Variance: {snap.get('price_variance', 'N/A')}"

        )



    def _verify_trade_case(case: Dict) -> Optional[Dict]:

        case_id = case["case_id"]

        logger.info("Trade AI verifier: processing %s | status=%s", case_id, case.get("reconciliation_status"))



        user_prompt = _build_trade_prompt(case)



        try:

            if provider == "anthropic":

                response = _anthropic_client.messages.create(

                    model=model, system=TRADE_SYSTEM_PROMPT,

                    messages=[{"role": "user", "content": user_prompt}],

                    max_tokens=max_tok,

                )

                raw = response.content[0].text

            else:

                response = _openai_client.chat.completions.create(

                    model=model,

                    messages=[

                        {"role": "system", "content": TRADE_SYSTEM_PROMPT},

                        {"role": "user", "content": user_prompt},

                    ],

                    response_format={"type": "json_object"},

                    temperature=0, max_tokens=max_tok,

                )

                raw = response.choices[0].message.content



            raw = raw.strip()

            raw = re.sub(r'^```(?:json)?\s*', '', raw)

            raw = re.sub(r'\s*```$', '', raw).strip()



            try:

                result = json.loads(raw)

            except json.JSONDecodeError as e:

                logger.error("Trade AI verifier: %s JSON parse failed — %s", case_id, e)

                return None



            verdict = result.get("verdict", "CAUTION")

            if verdict not in ("AGREE", "CAUTION", "DISAGREE"):

                verdict = "CAUTION"



            annotation = {

                "verdict": verdict,

                "confidence_pct": result.get("confidence_pct"),

                "diagnosis": result.get("diagnosis", ""),

                "root_cause": result.get("root_cause", ""),

                "recommended_action": result.get("recommended_action", ""),

                "routing_desk": result.get("routing_desk", ""),

                "note": result.get("diagnosis", ""),

                "verified_at": datetime.utcnow().isoformat(),

            }



            with get_conn() as conn:

                existing = conn.execute(

                    "SELECT feature_snapshot_json FROM recon_cases WHERE case_id = ?",

                    (case_id,),

                ).fetchone()

                snapshot = json.loads(existing["feature_snapshot_json"] or "{}") if existing else {}

                snapshot["ai_verification"] = annotation

                conn.execute(

                    "UPDATE recon_cases SET feature_snapshot_json = ?, updated_at = CURRENT_TIMESTAMP WHERE case_id = ?",

                    (json_dumps(snapshot), case_id),

                )

                conn.commit()



            logger.info("Trade AI verifier: %s -> verdict=%s confidence=%s%%", case_id, verdict, result.get("confidence_pct"))

            return {"case_id": case_id, **annotation}



        except Exception as exc:

            logger.error("Trade AI verifier: FAILED for %s (%s: %s)", case_id, type(exc).__name__, exc)

            return None



    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:

        futures = {executor.submit(_verify_trade_case, row): row for row in rows}

        for future in concurrent.futures.as_completed(futures):

            res = future.result()

            if res:

                results.append(res)



    logger.info("Trade AI verifier complete: phase_a=%d phase_b=%d/%d", len(phase_a_results), len(results), len(rows))

    return phase_a_results + results

