from __future__ import annotations
import logging
from dataclasses import asdict
from typing import Dict, List, Optional, Sequence
from .parsers import CcfTransaction, FixTransaction
from .reconciliation import ReconCase, aging_bucket, safe_date_diff

logger = logging.getLogger(__name__)


def _trade_features(fix: Optional[FixTransaction], ccf: Optional[CcfTransaction]) -> Dict:
    isin_match = bool(fix and ccf and fix.isin == ccf.isin)
    qty_match = bool(fix and ccf and abs(fix.quantity - ccf.quantity) < 0.01)
    qty_variance = round(fix.quantity - ccf.quantity, 2) if fix and ccf else None
    price_match = bool(fix and ccf and abs(fix.price - ccf.price) < 0.01)
    price_variance = round(fix.price - ccf.price, 2) if fix and ccf else None
    return {
        "fix_trade_id": fix.trade_id if fix else None,
        "ccf_clearing_ref": ccf.clearing_ref if ccf else None,
        "isin_match": isin_match,
        "quantity_match": qty_match,
        "quantity_variance": qty_variance,
        "price_match": price_match,
        "price_variance": price_variance,
        "side": fix.side if fix else None,
    }


def _trade_score_breakdown(feat: Dict, rule: str, confidence: int) -> Dict:
    components = []

    def add(name: str, passed: bool, weight: int, evidence: str) -> None:
        components.append({"component": name, "passed": passed, "weight": weight, "evidence": evidence})

    add("ISIN", feat.get("isin_match", False), 30,
        "ISIN matched" if feat.get("isin_match") else "ISIN mismatch")
    add("Quantity", feat.get("quantity_match", False), 30,
        "Quantity matched" if feat.get("quantity_match") else f"Variance: {feat.get('quantity_variance')}")
    add("Price", feat.get("price_match", False), 20,
        "Price matched" if feat.get("price_match") else f"Variance: {feat.get('price_variance')}")
    add("Side/Direction", feat.get("side") is not None, 20,
        f"Side: {feat.get('side')}" if feat.get("side") else "Side unknown")

    passed_weight = sum(c["weight"] for c in components if c["passed"])
    total_weight = sum(c["weight"] for c in components) or 1
    raw_score = round((passed_weight / total_weight) * 100, 2)
    matched = [c["component"] for c in components if c["passed"]]
    failed = [c["component"] for c in components if not c["passed"]]
    return {
        "rule_applied": rule,
        "engine_confidence": confidence,
        "raw_component_score": raw_score,
        "components": components,
        "matched_fields": matched,
        "failed_fields": failed,
        "decision_basis": f"{len(matched)} of {len(components)} fields matched (weighted score {raw_score}%). Confidence {confidence}% by {rule}.",
    }


def _build_trade_case(
    idx: int, fix: Optional[FixTransaction], ccf: Optional[CcfTransaction],
    status: str, reason: str, match_type: str, confidence: int, rule: str,
    exception_flag: str, explanation: str, suggestions: Optional[List[Dict]] = None,
    amount_override: Optional[tuple] = None,
) -> ReconCase:
    if amount_override:
        internal_amt, external_amt, variance = amount_override
    else:
        internal_amt = fix.quantity if fix else None
        external_amt = ccf.quantity if ccf else None
        variance = round(internal_amt - external_amt, 2) if internal_amt is not None and external_amt is not None else None
    value_dt = fix.transact_time[:10].replace("-", "") if fix else ""
    if fix and len(value_dt) >= 8 and value_dt.isdigit():
        value_dt = f"{value_dt[0:4]}-{value_dt[4:6]}-{value_dt[6:8]}"
    booking_dt = ccf.settlement_date if ccf else ""
    days = safe_date_diff(value_dt, booking_dt) if value_dt and booking_dt else 0
    feat = _trade_features(fix, ccf)
    feat["score_breakdown"] = _trade_score_breakdown(feat, rule, confidence)
    return ReconCase(
        case_id=f"TCASE-{idx:06d}",
        match_key=ccf.clearing_ref if ccf else (fix.trade_id if fix else f"TCASE-{idx:06d}"),
        psr_id=fix.exec_id if fix else "",
        camt_id=ccf.clearing_ref if ccf else "",
        reference=fix.exec_id if fix else "",
        invoice="",
        counterparty=ccf.exec_id if ccf else "",
        internal_amount=internal_amt,
        bank_amount=external_amt,
        variance=variance,
        currency=fix.currency if fix else "USD",
        value_date=value_dt,
        booking_date=booking_dt,
        reconciliation_status=status,
        reason_code=reason,
        match_type=match_type,
        match_confidence=confidence,
        aging_days=days,
        aging_bucket=aging_bucket(days),
        rule_applied=rule,
        exception_flag=exception_flag,
        explanation=explanation,
        feature_snapshot=feat,
        suggestions=suggestions or [],
    )


def reconcile_trades(
    fix_transactions: Sequence[FixTransaction],
    ccf_transactions: Sequence[CcfTransaction],
    quantity_tolerance: float = 0.01,
    price_tolerance: float = 1.00,
) -> List[ReconCase]:
    """Match front-office FIX executions against custodian CCF records by order reference."""
    logger.info("trade_reconciliation: fix=%d ccf=%d", len(fix_transactions), len(ccf_transactions))
    cases: List[ReconCase] = []
    idx = 1
    used_ccf: set = set()

    # Index CCF by order reference (clearing_ref) for direct join
    ccf_by_ref: Dict[str, CcfTransaction] = {}
    for ccf in ccf_transactions:
        ccf_by_ref[ccf.clearing_ref] = ccf

    for fix in fix_transactions:
        matched_ccf = ccf_by_ref.get(fix.exec_id)

        if matched_ccf:
            used_ccf.add(matched_ccf.clearing_ref)
            qty_match = abs(fix.quantity - matched_ccf.quantity) <= quantity_tolerance
            price_diff = abs(fix.price - matched_ccf.price)
            price_match = price_diff <= price_tolerance

            if qty_match and price_match:
                # T1: Order ref + qty + price all match → auto-close
                cases.append(_build_trade_case(
                    idx, fix, matched_ccf,
                    status="Matched & Settled (Auto-Close)",
                    reason="ORDER_REF_EXACT",
                    match_type="1_TO_1",
                    confidence=100,
                    rule="T1_ORDER_REF_EXACT",
                    exception_flag="N",
                    explanation=f"Order {fix.exec_id} matched by reference. ISIN {fix.isin}, quantity {fix.quantity:,.0f}, price ${fix.price:,.2f} confirmed by custodian.",
                ))
            elif qty_match and not price_match:
                # T2: Order ref + qty match but price break — show prices as amounts
                pvar = round(fix.price - matched_ccf.price, 2)
                cases.append(_build_trade_case(
                    idx, fix, matched_ccf,
                    status="Exception - Price Variance",
                    reason="PRICE_BREAK",
                    match_type="1_TO_1",
                    confidence=94,
                    rule="T2_PRICE_BREAK",
                    exception_flag="Y",
                    explanation=f"Order {fix.exec_id} matched by reference. Quantity confirmed but price differs: Front office ${fix.price:,.2f} vs Custodian ${matched_ccf.price:,.2f} (variance: {pvar:+,.2f}). Probable data entry error.",
                    suggestions=[{"action": "ROUTE_TO_REVIEW", "desk": "Mid-Office", "price_variance": pvar}],
                    amount_override=(fix.price, matched_ccf.price, pvar),
                ))
            else:
                # T3: Order ref match but quantity break
                var = round(fix.quantity - matched_ccf.quantity, 2)
                cases.append(_build_trade_case(
                    idx, fix, matched_ccf,
                    status="Exception - Quantity Mismatch",
                    reason="QUANTITY_MISMATCH",
                    match_type="1_TO_1",
                    confidence=75,
                    rule="T3_QUANTITY_BREAK",
                    exception_flag="Y",
                    explanation=f"Order {fix.exec_id} matched by reference. ISIN confirmed but quantity differs: Front office {fix.quantity:,.0f} vs Custodian {matched_ccf.quantity:,.0f} (variance: {var:+,.0f}). Partial allocation break.",
                    suggestions=[{"action": "ROUTE_TO_REVIEW", "desk": "Broker Allocation", "variance": var}],
                ))
            idx += 1
            continue

        # T4: Orphan FIX — no custodian record with this order reference
        cases.append(_build_trade_case(
            idx, fix, None,
            status="Exception - Unmatched Trade",
            reason="ORPHAN_FIX",
            match_type="UNMATCHED_TRADE",
            confidence=0,
            rule="T4_ORPHAN_TRADE",
            exception_flag="Y",
            explanation=f"Trade {fix.exec_id} (ISIN {fix.isin}, {fix.side} {fix.quantity:,.0f}) has no matching custodian record. Possible settlement failure or late confirmation.",
            suggestions=[{"action": "INVESTIGATE", "desk": "Operations", "trade_id": fix.exec_id}],
        ))
        idx += 1

    # T5: Orphan CCF records not matched to any trade
    for ccf in ccf_transactions:
        if ccf.clearing_ref in used_ccf:
            continue
        cases.append(_build_trade_case(
            idx, None, ccf,
            status="Exception - Unmatched Custodian Record",
            reason="ORPHAN_CCF",
            match_type="UNMATCHED_CUSTODIAN",
            confidence=0,
            rule="T5_ORPHAN_CUSTODIAN",
            exception_flag="Y",
            explanation=f"Custodian record {ccf.clearing_ref} (ISIN {ccf.isin}, {ccf.quantity:,.0f}) has no matching front-office trade. Possible unsolicited settlement or missing booking.",
            suggestions=[{"action": "INVESTIGATE", "desk": "Operations", "clearing_ref": ccf.clearing_ref}],
        ))
        idx += 1

    matched = sum(1 for c in cases if c.exception_flag == "N")
    exceptions = sum(1 for c in cases if c.exception_flag == "Y")
    logger.info("trade_reconciliation complete: %d cases (%d matched, %d exceptions)", len(cases), matched, exceptions)
    return cases


def trade_case_to_db_tuple(case: ReconCase) -> tuple:
    """Convert a trade ReconCase to a tuple for DB insertion (same schema as payment recon)."""
    import json
    return (
        case.case_id, case.match_key, case.psr_id, case.camt_id,
        case.reference, case.invoice, case.counterparty,
        case.internal_amount, case.bank_amount, case.variance,
        case.currency, case.value_date, case.booking_date,
        case.reconciliation_status, case.reason_code, case.match_type,
        case.match_confidence, case.aging_days, case.aging_bucket,
        case.rule_applied, case.exception_flag, case.explanation,
        json.dumps(case.feature_snapshot), json.dumps(case.suggestions),
        case.group_id, case.group_role,
        json.dumps(case.psr_members) if case.psr_members else None,
        json.dumps(case.camt_members) if case.camt_members else None,
    )
