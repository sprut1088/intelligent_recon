from __future__ import annotations
import logging
from dataclasses import dataclass, asdict
from datetime import date
from itertools import combinations as _combinations
from rapidfuzz import fuzz as _rfuzz
from typing import Dict, List, Optional, Sequence, Tuple
import json
from .config import settings
from .parsers import CamtTransaction, PsrTransaction, invoice_suffix

logger = logging.getLogger(__name__)

@dataclass
class ReconCase:
    case_id: str; match_key: str; psr_id: str; camt_id: str; reference: str; invoice: str; counterparty: str
    internal_amount: Optional[float]; bank_amount: Optional[float]; variance: Optional[float]; currency: str; value_date: str; booking_date: str
    reconciliation_status: str; reason_code: str; match_type: str; match_confidence: int; aging_days: int; aging_bucket: str; rule_applied: str; exception_flag: str
    explanation: str; feature_snapshot: Dict; suggestions: List[Dict]
    group_id: Optional[str] = None
    group_role: Optional[str] = None

def amount_equal(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and abs(left - right) <= settings.exact_amount_tolerance

def amount_variance(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None: return None
    return round(float(left) - float(right), 2)

def similarity(left: str, right: str) -> float:
    """Token-set aware similarity. Handles legal entity suffixes (Ltd, plc, Group).
    Returns 0.0–1.0. Uses max of token_set_ratio and WRatio."""
    a = (left or "").upper()
    b = (right or "").upper()
    ts = _rfuzz.token_set_ratio(a, b) / 100.0
    wr = _rfuzz.WRatio(a, b) / 100.0
    return max(ts, wr)

def aging_bucket(days: int) -> str:
    if days <= 1: return "0-1 Days"
    if days <= 2: return "2 Days"
    if days <= 5: return "3-5 Days"
    return "6+ Days"

def safe_date_diff(value_date: str, booking_date: str) -> int:
    try: return abs((date.fromisoformat(booking_date) - date.fromisoformat(value_date)).days)
    except Exception: return 0

def features(psr: Optional[PsrTransaction], bank: Optional[CamtTransaction]) -> Dict:
    return {"psr_id": psr.id if psr else None, "bank_id": bank.camt_id if bank else None, "end_to_end_id_exact": bool(psr and bank and psr.id == bank.end_to_end_id), "pmt_ref_exact": bool(psr and bank and psr.reference == bank.pmt_ref), "invoice_exact": bool(psr and bank and psr.invoice == bank.invoice), "invoice_suffix_match": bool(psr and bank and invoice_suffix(psr.invoice) and invoice_suffix(psr.invoice) == invoice_suffix(bank.invoice)), "amount_exact": bool(psr and bank and amount_equal(psr.amount, bank.amount)), "currency_match": bool(psr and bank and psr.currency == bank.currency), "counterparty_similarity": round(similarity(psr.counterparty, bank.counterparty), 4) if psr and bank else 0, "amount_variance": amount_variance(psr.amount, bank.amount) if psr and bank else None}


def score_breakdown(feature_map: Dict, rule: str, confidence: int) -> Dict:
    components = []

    def add(component: str, passed: bool, weight: int, evidence: str) -> None:
        components.append({
            "component": component,
            "passed": bool(passed),
            "weight": weight,
            "evidence": evidence,
        })

    add("Reference", feature_map.get("end_to_end_id_exact") or feature_map.get("pmt_ref_exact"), 30,
        "EndToEndId or PMT-REF matched" if feature_map.get("end_to_end_id_exact") or feature_map.get("pmt_ref_exact") else "No exact reference match")
    add("Amount", feature_map.get("amount_exact"), 25,
        "Amount matched exactly" if feature_map.get("amount_exact") else f"Variance: {feature_map.get('amount_variance')}")
    add("Invoice", feature_map.get("invoice_exact") or feature_map.get("invoice_suffix_match"), 20,
        "Invoice exact/suffix match" if feature_map.get("invoice_exact") or feature_map.get("invoice_suffix_match") else "Invoice did not match or was missing")
    add("Counterparty", (feature_map.get("counterparty_similarity") or 0) >= 0.85, 15,
        f"Counterparty similarity: {round((feature_map.get('counterparty_similarity') or 0) * 100, 2)}%")
    add("Currency", feature_map.get("currency_match"), 10,
        "Currency matched" if feature_map.get("currency_match") else "Currency did not match or one side is missing")

    passed_weight = sum(item["weight"] for item in components if item["passed"])
    total_weight = sum(item["weight"] for item in components) or 1
    raw_score = round((passed_weight / total_weight) * 100, 2)
    matched_fields = [item["component"] for item in components if item["passed"]]
    failed_fields = [item["component"] for item in components if not item["passed"]]
    return {
        "rule_applied": rule,
        "engine_confidence": confidence,
        "raw_component_score": raw_score,
        "components": components,
        "matched_fields": matched_fields,
        "failed_fields": failed_fields,
        "decision_basis": f"{len(matched_fields)} of {len(components)} fields matched (weighted score {raw_score}%). Confidence set to {confidence}% by {rule}.",
    }

def build_case(idx:int, psr: Optional[PsrTransaction], bank: Optional[CamtTransaction], status: str, reason: str, match_type: str, confidence:int, rule:str, exception_flag:str, explanation:str, suggestions: Optional[List[Dict]]=None) -> ReconCase:
    internal = psr.amount if psr else None; bank_amt = bank.amount if bank else None
    variance = amount_variance(internal, bank_amt) if bank and psr else (internal if psr else bank_amt)
    value_dt = psr.execution_date if psr else (bank.value_date if bank else ""); booking_dt = bank.booking_date if bank else ""
    days = safe_date_diff(value_dt, booking_dt) if value_dt and booking_dt else settings.in_transit_days
    feature_map = features(psr, bank)
    feature_map["score_breakdown"] = score_breakdown(feature_map, rule, confidence)
    return ReconCase(f"CASE-{idx:06d}", bank.ntry_id if bank else (psr.id if psr else f"CASE-{idx:06d}"), psr.id if psr else "", bank.camt_id if bank else "", psr.reference if psr else (bank.pmt_ref if bank else ""), psr.invoice if psr else (bank.invoice if bank else ""), psr.counterparty if psr else (bank.counterparty if bank else ""), internal, bank_amt, variance, psr.currency if psr else (bank.currency if bank else "EUR"), value_dt, booking_dt, status, reason, match_type, confidence, days, aging_bucket(days), rule, exception_flag, explanation, feature_map, suggestions or [])


def pattern_config(pattern_registry_rows: Sequence[Dict]) -> Dict[str, Dict]:
    config = {}
    for row in pattern_registry_rows:
        rule = row.get("pattern_rule")
        if rule is None:
            try:
                rule = json.loads(row.get("pattern_rule_json") or "{}")
            except json.JSONDecodeError:
                rule = {}
        config[row.get("pattern_id")] = {**row, "rule": rule or {}}
    return config


def pattern_is_active(config: Dict[str, Dict], pattern_id: str) -> bool:
    row = config.get(pattern_id)
    return not row or row.get("status") == "ACTIVE"


def pattern_rule_value(config: Dict[str, Dict], pattern_id: str, key: str, default):
    row = config.get(pattern_id) or {}
    rule = row.get("rule") or {}
    return rule.get(key, default)

def active_learned_patterns(pattern_registry_rows: Sequence[Dict]) -> List[Dict]:
    out=[]
    for row in pattern_registry_rows:
        if row.get("status") == "ACTIVE" and row.get("pattern_type") == "LEARNED":
            try: rule = json.loads(row.get("pattern_rule_json") or "{}")
            except json.JSONDecodeError: rule = {}
            out.append({**row, "rule": rule})
    return out

def learned_invoice_suffix_match(psr: PsrTransaction, banks: Sequence[CamtTransaction], used: set, learned: Sequence[Dict]) -> Optional[Tuple[CamtTransaction, Dict]]:
    if not any("Invoice Suffix" in p.get("pattern_name", "") for p in learned): return None
    suffix = invoice_suffix(psr.invoice)
    if not suffix: return None
    for bank in banks:
        if bank.ntry_id in used: continue
        if suffix == invoice_suffix(bank.invoice) and amount_equal(psr.amount, bank.amount):
            score = min(round(0.90 + 0.08 * similarity(psr.counterparty, bank.counterparty), 3), 0.98)
            return bank, {"pattern": "P8 Invoice Suffix Normalisation", "score": score, "reason": "Approved learned pattern matched invoice suffix + amount + counterparty similarity."}
    return None

# ── P6 One-to-Many helpers ─────────────────────────────────────────────────────

def _find_subset_matches(
    psrs: List[PsrTransaction],
    target: float,
    max_size: int,
    tolerance: float,
) -> List[List[PsrTransaction]]:
    """Return up to 2 sorted PSR subsets whose amounts sum to target within tolerance.
    Sorted deterministically: earliest execution_date, tiebreak psr_id asc.
    Returns at most 2 results so callers can detect ambiguity without searching further."""
    results: List[List[PsrTransaction]] = []
    for size in range(2, min(max_size, len(psrs)) + 1):
        for combo in _combinations(psrs, size):
            if abs(sum(p.amount for p in combo) - target) <= tolerance:
                sorted_combo = sorted(combo, key=lambda p: (p.execution_date or "", p.id))
                results.append(list(sorted_combo))
                if len(results) >= 2:
                    return results  # enough to detect ambiguity — stop early
        if results:
            return results  # found matches at this size; don't try larger subsets
    return results


def _record_group(
    groups: List[Dict],
    used_psr_ids: set,
    used_camt_ids: set,
    camt: CamtTransaction,
    chosen: List[PsrTransaction],
    alternative: Optional[List[PsrTransaction]],
    confidence: int,
    rule_applied: str,
    reason_code: str,
    explanation: str,
    group_variance: float,
    ambiguous: bool,
) -> None:
    """Append a group descriptor and mark its PSRs/CAMT as consumed."""
    used_camt_ids.add(camt.ntry_id)
    for p in chosen:
        used_psr_ids.add(p.id)
    groups.append({
        "camt":             camt,
        "psrs":             chosen,
        "anchor_psr":       chosen[0],
        "confidence":       confidence,
        "rule_applied":     rule_applied,
        "reason_code":      reason_code,
        "explanation":      explanation,
        "ambiguous":        ambiguous,
        "group_variance":   group_variance,
        "alternative_psrs": alternative,
    })


def find_one_to_many_groups(
    residual_psrs: List[PsrTransaction],
    residual_camts: List[CamtTransaction],
    config: Dict[str, Dict],
) -> List[Dict]:
    """Find groups of PSR transactions whose amounts sum to a single CAMT entry.

    Returns a list of group dicts with keys:
        camt, psrs, anchor_psr, confidence, rule_applied, reason_code,
        explanation, ambiguous, group_variance, alternative_psrs
    """
    if not pattern_is_active(config, "P6"):
        return []

    cp_threshold = float(pattern_rule_value(config, "P6", "counterparty_threshold", 0.85))
    max_grp_size = int(pattern_rule_value(config, "P6", "max_group_size", 6))
    date_window  = int(pattern_rule_value(config, "P6", "date_window_days", 3))
    var_subpass  = bool(pattern_rule_value(config, "P6", "variance_subpass_enabled", True))
    var_max_size = int(pattern_rule_value(config, "P6", "variance_subpass_max_group_size", 3))

    groups: List[Dict] = []
    used_psr_ids: set = set()
    used_camt_ids: set = set()

    for camt in residual_camts:
        if camt.ntry_id in used_camt_ids or camt.amount is None:
            continue

        # Step 1: narrow PSR pool by direction + counterparty similarity + date window
        candidates = [
            p for p in residual_psrs
            if p.id not in used_psr_ids
            and p.direction == camt.direction
            and similarity(p.counterparty, camt.counterparty) >= cp_threshold
            and safe_date_diff(p.execution_date or "", camt.booking_date or "") <= date_window
        ]
        if len(candidates) < 2:
            continue

        # Step 2: exact subset-sum
        exact_matches = _find_subset_matches(
            candidates, camt.amount, max_grp_size, settings.exact_amount_tolerance
        )
        if exact_matches:
            chosen    = exact_matches[0]
            ambiguous = len(exact_matches) > 1
            alt       = exact_matches[1] if ambiguous else None
            conf      = 72 if ambiguous else 88
            rule      = "P6_BANK_BATCH_GROUPING_AMBIGUOUS" if ambiguous else "P6_BANK_BATCH_GROUPING"
            reason    = "BANK_BATCH_GROUPING_AMBIGUOUS" if ambiguous else "BANK_BATCH_GROUPING"
            psr_ids_str = ", ".join(p.id for p in chosen)
            expl = (
                f"{'Ambiguous: multiple valid groupings. Selected by earliest date. ' if ambiguous else ''}"
                f"{len(chosen)} PSR transactions ({psr_ids_str}) sum to "
                f"{sum(p.amount for p in chosen):.2f} = CAMT {camt.ntry_id} ({camt.amount:.2f}). "
                f"Counterparty similarity confirmed."
            )
            if ambiguous and alt:
                expl += f" Alternative grouping: {', '.join(p.id for p in alt)}."
            _record_group(groups, used_psr_ids, used_camt_ids, camt, chosen, alt,
                          conf, rule, reason, expl, 0.0, ambiguous)
            continue

        # Step 3: variance sub-pass (small groups only)
        if var_subpass and len(candidates) >= 2:
            var_matches = _find_subset_matches(
                candidates, camt.amount, var_max_size, settings.minor_variance_tolerance
            )
            if var_matches:
                chosen      = var_matches[0]
                group_sum   = sum(p.amount for p in chosen)
                grp_var     = round(group_sum - camt.amount, 2)
                psr_ids_str = ", ".join(p.id for p in chosen)
                expl = (
                    f"{len(chosen)} PSR transactions ({psr_ids_str}) sum to "
                    f"{group_sum:.2f} vs CAMT {camt.ntry_id} ({camt.amount:.2f}). "
                    f"Variance {grp_var:+.2f} is within minor tolerance. "
                    f"Post to short/over ledger."
                )
                _record_group(groups, used_psr_ids, used_camt_ids, camt, chosen, None,
                              78, "P6_BATCH_MINOR_VARIANCE", "AMOUNT_VARIANCE_MINOR_BATCH",
                              expl, grp_var, False)

    return groups

# ── End P6 helpers ─────────────────────────────────────────────────────────────

def reconcile_transactions(psr_transactions: Sequence[PsrTransaction], camt_transactions: Sequence[CamtTransaction], pattern_registry_rows: Sequence[Dict]) -> List[ReconCase]:
    logger.info("reconcile_transactions: psr=%d camt=%d patterns=%d", len(psr_transactions), len(camt_transactions), len(pattern_registry_rows))
    cases=[]; used=set(); idx=1; p5_pending: List[PsrTransaction]=[]
    config = pattern_config(pattern_registry_rows)
    p4_threshold = float(pattern_rule_value(config, "P4", "threshold", 0.85))
    p7_minor_tolerance = float(pattern_rule_value(config, "P7", "minor_tolerance", settings.minor_variance_tolerance))
    by_e2e={b.end_to_end_id:b for b in camt_transactions if b.end_to_end_id}
    by_ref_amt={}; by_inv_amt={}; by_inv={}; by_amt={}
    for b in camt_transactions:
        if b.pmt_ref: by_ref_amt.setdefault((b.pmt_ref,b.amount),[]).append(b)
        if b.invoice: by_inv_amt.setdefault((b.invoice,b.amount),[]).append(b)
        if b.invoice: by_inv.setdefault(b.invoice,[]).append(b)
        by_amt.setdefault(b.amount,[]).append(b)
    learned = active_learned_patterns(pattern_registry_rows)
    for psr in psr_transactions:
        bank = by_e2e.get(psr.id)
        if pattern_is_active(config, "P1") and bank and bank.ntry_id not in used:
            var = amount_variance(psr.amount, bank.amount) or 0
            if amount_equal(psr.amount, bank.amount):
                status, reason, conf, rule, flag, expl = "Matched & Settled (Auto-Close)", "EXACT_MATCH", 100, "P1_EXACT_END_TO_END_ID", "N", "Exact EndToEndId match and exact amount match. Auto-close is safe."
                sugg=[]
            elif pattern_is_active(config, "P7") and abs(var) <= p7_minor_tolerance:
                status, reason, conf, rule, flag, expl = "Post to Short or Over Ledger", "AMOUNT_VARIANCE_MINOR", 86, "P7_AMOUNT_VARIANCE", "Y", f"Identity matched but amount variance {var} is within configured minor tolerance."
                sugg=[{"action":"POST_LEDGER_CANDIDATE","confidence":0.86,"variance":var}]
            else:
                status, reason, conf, rule, flag, expl = "Exception - Amount Variance Review", "AMOUNT_VARIANCE_MAJOR", 70, "P7_AMOUNT_VARIANCE", "Y", f"Identity matched but amount variance {var} exceeds configured tolerance."
                sugg=[{"action":"ROUTE_TO_REVIEW","confidence":0.70,"variance":var}]
            used.add(bank.ntry_id); cases.append(build_case(idx, psr, bank, status, reason, "1_TO_1", conf, rule, flag, expl, sugg)); idx+=1; continue
        secondary = next((b for b in by_ref_amt.get((psr.reference,psr.amount),[]) if b.ntry_id not in used), None)
        if pattern_is_active(config, "P2") and secondary:
            used.add(secondary.ntry_id); cases.append(build_case(idx, psr, secondary, "Matched & Settled (Auto-Close)", "PMT_REF_AMOUNT_MATCH", "1_TO_1", 96, "P2_PMT_REF_AMOUNT", "N", "EndToEndId was not available or did not match, but PMT-REF and amount matched.")); idx+=1; continue
        inv = next((b for b in by_inv_amt.get((psr.invoice,psr.amount),[]) if b.ntry_id not in used), None)
        if pattern_is_active(config, "P3") and inv:
            used.add(inv.ntry_id); cases.append(build_case(idx, psr, inv, "Matched & Settled (Auto-Close)", "INVOICE_AMOUNT_MATCH", "1_TO_1", 92, "P3_INVOICE_USTRD_AMOUNT", "N", "Invoice extracted from CAMT remittance matched PSR invoice and amount.")); idx+=1; continue
        inv_near = next((b for b in by_inv.get(psr.invoice or "", []) if b.ntry_id not in used and abs((amount_variance(psr.amount, b.amount) or 0)) <= p7_minor_tolerance), None) if psr.invoice else None
        if pattern_is_active(config, "P3") and pattern_is_active(config, "P7") and inv_near:
            var = amount_variance(psr.amount, inv_near.amount) or 0
            used.add(inv_near.ntry_id); cases.append(build_case(idx, psr, inv_near, "Post to Short or Over Ledger", "INVOICE_MATCH_AMOUNT_VARIANCE_MINOR", "1_TO_1", 86, "P3_P7_INVOICE_MINOR_VARIANCE", "Y", f"Invoice matched but amount variance {var} is within configured minor tolerance. Post to short/over ledger.", [{"action":"POST_LEDGER_CANDIDATE","confidence":0.86,"variance":var}])); idx+=1; continue
        learned_match = learned_invoice_suffix_match(psr, camt_transactions, used, learned)
        if learned_match:
            lb, s = learned_match; used.add(lb.ntry_id); cases.append(build_case(idx, psr, lb, "Suggested Match - Learned Pattern", "LEARNED_INVOICE_SUFFIX", "1_TO_1", 90, "P8_LEARNED_INVOICE_SUFFIX", "Y", "Approved learned pattern suggested this match. Analyst confirmation is required.", [{"action":"CONFIRM_LEARNED_MATCH", **s}])); idx+=1; continue
        # P4 (fuzzy 1-to-1) deliberately deferred to a post-P6 pass — see TASK-34.
        # PSRs that belong to a P6 batch group must not be cannibalised by P4 fuzzy matching first.
        p5_pending.append(psr)  # stage for P6 + post-P6 P4 pass before emitting P5

    # ── P6 One-to-Many residual-pool pass (runs BEFORE P4 — TASK-34) ──────────
    p6_consumed_psr_ids: set = set()
    p6_groups: List[Dict] = []
    if pattern_is_active(config, "P6") and p5_pending:
        residual_camts = [b for b in camt_transactions if b.ntry_id not in used]
        p6_groups = find_one_to_many_groups(p5_pending, residual_camts, config)

        for grp in p6_groups:
            grp_id     = f"GRP-{idx:06d}"
            camt_b     = grp["camt"]
            psrs_g     = grp["psrs"]   # anchor-first (sorted by date/id)
            conf_g     = grp["confidence"]
            rule_g     = grp["rule_applied"]
            reason_g   = grp["reason_code"]
            expl_g     = grp["explanation"]
            grp_var    = grp["group_variance"]
            group_sum  = round(sum(p.amount for p in psrs_g), 2)

            if rule_g == "P6_BATCH_MINOR_VARIANCE":
                status_g = "Post to Short or Over Ledger"
            elif rule_g == "P6_BANK_BATCH_GROUPING_AMBIGUOUS":
                status_g = "Suggested Match - Analyst Review"
            else:
                status_g = "Suggested Match - Group Settlement"

            anchor_case_id = f"CASE-{idx:06d}"

            for pos, psr_g in enumerate(psrs_g):
                is_anchor  = (pos == 0)
                this_case_id = f"CASE-{idx:06d}"
                days_g     = safe_date_diff(psr_g.execution_date or "", camt_b.booking_date or "")

                if is_anchor:
                    feat = {
                        "group_id": grp_id, "group_role": "ANCHOR",
                        "n_psrs_in_group": len(psrs_g), "sum_of_psr_amounts": group_sum,
                        "counterparty_consensus_similarity": round(
                            sum(similarity(p.counterparty, camt_b.counterparty) for p in psrs_g) / len(psrs_g), 4),
                        "max_date_spread_days": max(
                            safe_date_diff(p.execution_date or "", camt_b.booking_date or "") for p in psrs_g),
                        "is_ambiguous": grp["ambiguous"], "group_variance": grp_var,
                        "score_breakdown": score_breakdown(
                            {"amount_exact": grp_var == 0.0, "currency_match": True,
                             "counterparty_similarity": 0.9, "end_to_end_id_exact": False,
                             "pmt_ref_exact": False, "invoice_exact": False,
                             "invoice_suffix_match": False, "amount_variance": grp_var},
                            rule_g, conf_g),
                    }
                    if grp["ambiguous"] and grp["alternative_psrs"]:
                        feat["alternative_group_psr_ids"] = [p.id for p in grp["alternative_psrs"]]
                    sugg_g = [{"action": "CONFIRM_GROUP_MATCH", "confidence": conf_g / 100.0,
                               "group_id": grp_id, "group_psr_ids": [p.id for p in psrs_g],
                               "camt_id": camt_b.camt_id}]
                    rc = ReconCase(
                        case_id=this_case_id, match_key=camt_b.ntry_id,
                        psr_id=psr_g.id, camt_id=camt_b.camt_id,
                        reference=psr_g.reference, invoice=psr_g.invoice,
                        counterparty=psr_g.counterparty,
                        internal_amount=group_sum,  # group sum on anchor
                        bank_amount=camt_b.amount,
                        variance=round(group_sum - (camt_b.amount or 0), 2),
                        currency=psr_g.currency,
                        value_date=psr_g.execution_date or "", booking_date=camt_b.booking_date or "",
                        reconciliation_status=status_g, reason_code=reason_g,
                        match_type="N_TO_1", match_confidence=conf_g,
                        aging_days=days_g, aging_bucket=aging_bucket(days_g),
                        rule_applied=rule_g, exception_flag="Y",
                        explanation=expl_g, feature_snapshot=feat, suggestions=sugg_g,
                        group_id=grp_id, group_role="ANCHOR",
                    )
                else:
                    feat = {"group_member": True, "group_id": grp_id, "anchor_case_id": anchor_case_id}
                    mem_expl = (f"Part of group {grp_id} ({len(psrs_g)} PSRs sum to "
                                f"{group_sum:.2f} = CAMT {camt_b.ntry_id} {camt_b.amount:.2f}). "
                                f"See anchor case {anchor_case_id}.")
                    rc = ReconCase(
                        case_id=this_case_id, match_key=camt_b.ntry_id,
                        psr_id=psr_g.id, camt_id=camt_b.camt_id,
                        reference=psr_g.reference, invoice=psr_g.invoice,
                        counterparty=psr_g.counterparty,
                        internal_amount=psr_g.amount,  # individual amount on members
                        bank_amount=None, variance=None,
                        currency=psr_g.currency,
                        value_date=psr_g.execution_date or "", booking_date=camt_b.booking_date or "",
                        reconciliation_status=status_g, reason_code=reason_g,
                        match_type="N_TO_1", match_confidence=conf_g,
                        aging_days=days_g, aging_bucket=aging_bucket(days_g),
                        rule_applied=rule_g, exception_flag="Y",
                        explanation=mem_expl, feature_snapshot=feat, suggestions=[],
                        group_id=grp_id, group_role="MEMBER",
                    )

                cases.append(rc)
                idx += 1
                p6_consumed_psr_ids.add(psr_g.id)

            used.add(camt_b.ntry_id)

    # Post-P6 residual: PSRs that did not land in a P6 group
    post_p6_residual = [psr for psr in p5_pending if psr.id not in p6_consumed_psr_ids]

    # ── P4 fuzzy 1-to-1 pass (runs AFTER P6 — TASK-34) ─────────────────────────
    # Lifted out of the per-PSR loop so P6 has first refusal on residuals.
    # P6 uses stronger evidence (subset-sum + counterparty + date window) and should
    # outrank P4 (fuzzy name + amount only). Without this ordering, P4 cannibalises
    # batch members whose individual amount coincidentally matches an unrelated CAMT.
    p4_consumed_psr_ids: set = set()
    if pattern_is_active(config, "P4") and post_p6_residual:
        for psr in post_p6_residual:
            cands = [b for b in by_amt.get(psr.amount, []) if b.ntry_id not in used]
            fuzzy = None; score = 0.0
            for b in cands:
                sc = similarity(psr.counterparty, b.counterparty)
                if sc > score:
                    fuzzy, score = b, sc
            if fuzzy and score >= p4_threshold:
                used.add(fuzzy.ntry_id)
                cases.append(build_case(
                    idx, psr, fuzzy, "Suggested Match - Analyst Review",
                    "COUNTERPARTY_FUZZY_AMOUNT", "1_TO_1", int(score * 100),
                    "P4_COUNTERPARTY_FUZZY", "Y",
                    f"Counterparty similarity {score:.2f} with exact amount. Requires analyst confirmation.",
                    [{"action": "REVIEW_FUZZY_CANDIDATE", "confidence": round(score, 3),
                      "bank_id": fuzzy.camt_id}],
                ))
                idx += 1
                p4_consumed_psr_ids.add(psr.id)

    # ── P5 exception emission for everything still unmatched ───────────────────
    for psr in post_p6_residual:
        if psr.id in p4_consumed_psr_ids:
            continue
        cases.append(build_case(idx, psr, None, "Uncleared / In-Transit Payment",
            "NO_ACCEPTABLE_CANDIDATES", "UNMATCHED_PSR", 45, "P5_EXCEPTION_HANDLING", "Y",
            "No acceptable bank candidate was found. Route to exception queue and monitor next CAMT cycle.",
            [{"action": "ROUTE_TO_EXCEPTION_QUEUE", "confidence": 0.45,
              "expected_clear_days": settings.in_transit_days}]))
        idx += 1
    # ── End P6 + P4 + P5 residual pass ─────────────────────────────────────────

    for bank in camt_transactions:
        if bank.ntry_id in used: continue
        cases.append(build_case(idx, None, bank, "Bank-only Item - Investigation", "BANK_ONLY_UNMATCHED", "UNMATCHED_BANK", 40, "P5_EXCEPTION_HANDLING", "Y", "Bank entry was present in CAMT but no matching expected payment was found in PSR.", [{"action":"INVESTIGATE_BANK_ONLY","confidence":0.40}])); idx+=1
    exceptions = sum(1 for c in cases if c.exception_flag == "Y")
    logger.info("reconcile_transactions done: %d cases, %d exceptions (p6_groups=%d, p4_matches=%d)",
                len(cases), exceptions, len(p6_groups), len(p4_consumed_psr_ids))
    return cases

def case_to_db_tuple(case: ReconCase) -> tuple:
    p=asdict(case)
    return (p["case_id"],p["match_key"],p["psr_id"],p["camt_id"],p["reference"],p["invoice"],p["counterparty"],p["internal_amount"],p["bank_amount"],p["variance"],p["currency"],p["value_date"],p["booking_date"],p["reconciliation_status"],p["reason_code"],p["match_type"],p["match_confidence"],p["aging_days"],p["aging_bucket"],p["rule_applied"],p["exception_flag"],p["explanation"],json.dumps(p["feature_snapshot"]),json.dumps(p["suggestions"]),p["group_id"],p["group_role"])
