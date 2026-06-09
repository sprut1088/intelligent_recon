from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple
import json
from .config import settings
from .parsers import CamtTransaction, PsrTransaction, invoice_suffix

@dataclass
class ReconCase:
    case_id: str; match_key: str; psr_id: str; camt_id: str; reference: str; invoice: str; counterparty: str
    internal_amount: Optional[float]; bank_amount: Optional[float]; variance: Optional[float]; currency: str; value_date: str; booking_date: str
    reconciliation_status: str; reason_code: str; match_type: str; match_confidence: int; aging_days: int; aging_bucket: str; rule_applied: str; exception_flag: str
    explanation: str; feature_snapshot: Dict; suggestions: List[Dict]

def amount_equal(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and abs(left - right) <= settings.exact_amount_tolerance

def amount_variance(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None: return None
    return round(float(left) - float(right), 2)

def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, (left or "").upper(), (right or "").upper()).ratio()

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

def build_case(idx:int, psr: Optional[PsrTransaction], bank: Optional[CamtTransaction], status: str, reason: str, match_type: str, confidence:int, rule:str, exception_flag:str, explanation:str, suggestions: Optional[List[Dict]]=None) -> ReconCase:
    internal = psr.amount if psr else None; bank_amt = bank.amount if bank else None
    variance = amount_variance(internal, bank_amt) if bank and psr else (internal if psr else bank_amt)
    value_dt = psr.execution_date if psr else (bank.value_date if bank else ""); booking_dt = bank.booking_date if bank else ""
    days = safe_date_diff(value_dt, booking_dt) if value_dt and booking_dt else settings.in_transit_days
    return ReconCase(f"CASE-{idx:06d}", bank.ntry_id if bank else (psr.id if psr else f"CASE-{idx:06d}"), psr.id if psr else "", bank.camt_id if bank else "", psr.reference if psr else (bank.pmt_ref if bank else ""), psr.invoice if psr else (bank.invoice if bank else ""), psr.counterparty if psr else (bank.counterparty if bank else ""), internal, bank_amt, variance, psr.currency if psr else (bank.currency if bank else "EUR"), value_dt, booking_dt, status, reason, match_type, confidence, days, aging_bucket(days), rule, exception_flag, explanation, features(psr, bank), suggestions or [])

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

def reconcile_transactions(psr_transactions: Sequence[PsrTransaction], camt_transactions: Sequence[CamtTransaction], pattern_registry_rows: Sequence[Dict]) -> List[ReconCase]:
    cases=[]; used=set(); idx=1
    by_e2e={b.end_to_end_id:b for b in camt_transactions if b.end_to_end_id}
    by_ref_amt={}; by_inv_amt={}; by_amt={}
    for b in camt_transactions:
        if b.pmt_ref: by_ref_amt.setdefault((b.pmt_ref,b.amount),[]).append(b)
        if b.invoice: by_inv_amt.setdefault((b.invoice,b.amount),[]).append(b)
        by_amt.setdefault(b.amount,[]).append(b)
    learned = active_learned_patterns(pattern_registry_rows)
    for psr in psr_transactions:
        bank = by_e2e.get(psr.id)
        if bank and bank.ntry_id not in used:
            var = amount_variance(psr.amount, bank.amount) or 0
            if amount_equal(psr.amount, bank.amount):
                status, reason, conf, rule, flag, expl = "Matched & Settled (Auto-Close)", "EXACT_MATCH", 100, "P1_EXACT_END_TO_END_ID", "N", "Exact EndToEndId match and exact amount match. Auto-close is safe."
                sugg=[]
            elif abs(var) <= settings.minor_variance_tolerance:
                status, reason, conf, rule, flag, expl = "Post to Short or Over Ledger", "AMOUNT_VARIANCE_MINOR", 86, "P7_AMOUNT_VARIANCE", "Y", f"Identity matched but amount variance {var} is within configured minor tolerance."
                sugg=[{"action":"POST_LEDGER_CANDIDATE","confidence":0.86,"variance":var}]
            else:
                status, reason, conf, rule, flag, expl = "Exception - Amount Variance Review", "AMOUNT_VARIANCE_MAJOR", 70, "P7_AMOUNT_VARIANCE", "Y", f"Identity matched but amount variance {var} exceeds configured tolerance."
                sugg=[{"action":"ROUTE_TO_REVIEW","confidence":0.70,"variance":var}]
            used.add(bank.ntry_id); cases.append(build_case(idx, psr, bank, status, reason, "1_TO_1", conf, rule, flag, expl, sugg)); idx+=1; continue
        secondary = next((b for b in by_ref_amt.get((psr.reference,psr.amount),[]) if b.ntry_id not in used), None)
        if secondary:
            used.add(secondary.ntry_id); cases.append(build_case(idx, psr, secondary, "Matched & Settled (Auto-Close)", "PMT_REF_AMOUNT_MATCH", "1_TO_1", 96, "P2_PMT_REF_AMOUNT", "N", "EndToEndId was not available or did not match, but PMT-REF and amount matched.")); idx+=1; continue
        inv = next((b for b in by_inv_amt.get((psr.invoice,psr.amount),[]) if b.ntry_id not in used), None)
        if inv:
            used.add(inv.ntry_id); cases.append(build_case(idx, psr, inv, "Matched & Settled (Auto-Close)", "INVOICE_AMOUNT_MATCH", "1_TO_1", 92, "P3_INVOICE_USTRD_AMOUNT", "N", "Invoice extracted from CAMT remittance matched PSR invoice and amount.")); idx+=1; continue
        learned_match = learned_invoice_suffix_match(psr, camt_transactions, used, learned)
        if learned_match:
            lb, s = learned_match; used.add(lb.ntry_id); cases.append(build_case(idx, psr, lb, "Suggested Match - Learned Pattern", "LEARNED_INVOICE_SUFFIX", "1_TO_1", 90, "P8_LEARNED_INVOICE_SUFFIX", "Y", "Approved learned pattern suggested this match. Analyst confirmation is required.", [{"action":"CONFIRM_LEARNED_MATCH", **s}])); idx+=1; continue
        cands=[b for b in by_amt.get(psr.amount,[]) if b.ntry_id not in used]
        fuzzy=None; score=0
        for b in cands:
            sc=similarity(psr.counterparty,b.counterparty)
            if sc>score: fuzzy,score=b,sc
        if fuzzy and score>=0.85:
            used.add(fuzzy.ntry_id); cases.append(build_case(idx, psr, fuzzy, "Suggested Match - Analyst Review", "COUNTERPARTY_FUZZY_AMOUNT", "1_TO_1", int(score*100), "P4_COUNTERPARTY_FUZZY", "Y", f"Counterparty similarity {score:.2f} with exact amount. Requires analyst confirmation.", [{"action":"REVIEW_FUZZY_CANDIDATE","confidence":round(score,3),"bank_id":fuzzy.camt_id}])); idx+=1; continue
        cases.append(build_case(idx, psr, None, "Uncleared / In-Transit Payment", "NO_ACCEPTABLE_CANDIDATES", "UNMATCHED_PSR", 45, "P5_EXCEPTION_HANDLING", "Y", "No acceptable bank candidate was found. Route to exception queue and monitor next CAMT cycle.", [{"action":"ROUTE_TO_EXCEPTION_QUEUE","confidence":0.45,"expected_clear_days":settings.in_transit_days}])); idx+=1
    for bank in camt_transactions:
        if bank.ntry_id in used: continue
        cases.append(build_case(idx, None, bank, "Bank-only Item - Investigation", "BANK_ONLY_UNMATCHED", "UNMATCHED_BANK", 40, "P5_EXCEPTION_HANDLING", "Y", "Bank entry was present in CAMT but no matching expected payment was found in PSR.", [{"action":"INVESTIGATE_BANK_ONLY","confidence":0.40}])); idx+=1
    return cases

def case_to_db_tuple(case: ReconCase) -> tuple:
    p=asdict(case)
    return (p["case_id"],p["match_key"],p["psr_id"],p["camt_id"],p["reference"],p["invoice"],p["counterparty"],p["internal_amount"],p["bank_amount"],p["variance"],p["currency"],p["value_date"],p["booking_date"],p["reconciliation_status"],p["reason_code"],p["match_type"],p["match_confidence"],p["aging_days"],p["aging_bucket"],p["rule_applied"],p["exception_flag"],p["explanation"],json.dumps(p["feature_snapshot"]),json.dumps(p["suggestions"]))
