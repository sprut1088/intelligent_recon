from __future__ import annotations
import difflib
import logging
import re
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
    group_id:      Optional[str]        = None
    group_role:    Optional[str]        = None
    psr_members:   Optional[List[Dict]] = None
    camt_members:  Optional[List[Dict]] = None

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


# ── Counterparty normalisation (TASK-35) ───────────────────────────────────────
# Used by P6 partitioning and (post TASK-37) by P4 fuzzy gate. Keep deterministic.

_LEGAL_SUFFIXES = {
    "llc", "inc", "co", "corp", "ltd", "gmbh", "pvt", "limited", "company",
    "plc", "ag", "sa", "nv", "bv", "kg", "ohg", "spa", "srl", "oy", "ab",
    "as", "aps", "sas", "sarl", "sl", "lp", "llp", "pte", "kk", "yk",
}
_PUNCT_RE = re.compile(r"[.,;:'\"\-_/\\()]")
_WS_RE = re.compile(r"\s+")


def normalise_counterparty(name: str) -> str:
    """Return a partition key for counterparty grouping.

    Lowercases, strips punctuation, collapses whitespace, drops common legal
    suffixes. Designed so that 'Acme LLC', 'acme', 'Acme, Inc.' all collapse
    to the same key, while preserving distinct names like 'Acme Holdings'.
    """
    if not name:
        return ""
    s = _PUNCT_RE.sub(" ", name.lower())
    s = _WS_RE.sub(" ", s).strip()
    tokens = [t for t in s.split(" ") if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def trailing_single_char_diff(a: str, b: str) -> bool:
    """True when two strings differ only in their final 1-2 alphanumeric chars.

    Catches sibling-entity name patterns like 'Batch Customer A' vs 'Batch
    Customer B', 'Branch 01' vs 'Branch 02'. These should never partition
    together in P6 and (post TASK-37) should never pass the P4 gate either.
    """
    if not a or not b or a == b:
        return False
    # Quick exit if lengths differ by more than 1 (single trailing char insert)
    if abs(len(a) - len(b)) > 1:
        return False
    # Find common prefix
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    rem_a, rem_b = a[i:], b[i:]
    if len(rem_a) > 2 or len(rem_b) > 2:
        return False
    # Differing chars must be alphanumeric and the common prefix non-trivial
    if i < 3:
        return False
    return all(c.isalnum() for c in rem_a + rem_b)


def shared_substring(a: Optional[str], b: Optional[str], min_len: int = 5) -> bool:
    """True when a and b share a contiguous substring of length >= min_len.

    Used by P4 (post TASK-37) as a corroboration signal: a fuzzy counterparty
    match alone is no longer enough — there must be a non-trivial shared chunk
    in the payment reference or invoice number for P4 to fire.
    """
    if not a or not b or min_len <= 0:
        return False
    sa, sb = str(a).strip().upper(), str(b).strip().upper()
    if len(sa) < min_len or len(sb) < min_len:
        return False
    m = difflib.SequenceMatcher(a=sa, b=sb, autojunk=False).find_longest_match(0, len(sa), 0, len(sb))
    return m.size >= min_len


_DEFAULT_BATCH_MARKER_REGEX = r"^(BATCH|BULK|CONSOL|RUN|PAYMENT[-_]?RUN)[-_]"


def is_bank_batch_marker(end_to_end_id: Optional[str], pattern: str = _DEFAULT_BATCH_MARKER_REGEX) -> bool:
    """True when a CAMT end_to_end_id looks like an explicit batch settlement marker.

    Used by P6 (post TASK-36) to seed marker-aware grouping: when the bank flags
    an entry as a batch (e.g. 'BATCH-GRP-A', 'BULK-2026-07'), P6 prefers that
    entry first and emits a higher-confidence group when the partition matches.
    """
    if not end_to_end_id:
        return False
    try:
        return bool(re.match(pattern, end_to_end_id.strip(), re.IGNORECASE))
    except re.error:
        logger.warning("Invalid P6.batch_marker_regex %r; falling back to default", pattern)
        return bool(re.match(_DEFAULT_BATCH_MARKER_REGEX, end_to_end_id.strip(), re.IGNORECASE))


# ── Split-settlement helpers (TASK-38) ─────────────────────────────────────────

_DEFAULT_SPLIT_MARKER_REGEX = r"\b(\d+)\s*(?:of|/)\s*(\d+)\b"


def detect_split_marker(text: Optional[str], pattern: str = _DEFAULT_SPLIT_MARKER_REGEX) -> Optional[Tuple[int, int]]:
    """Return (part_num, total_parts) if text contains a 'K of N' split marker.

    Used by P10 to recognise bank-side split-payment hints like '1 of 2', '2/3',
    'PART 1 OF 4'. The marker enriches the explanation; the linkage itself is
    via the shared PMT-REF/invoice between CAMTs.
    """
    if not text:
        return None
    try:
        m = re.search(pattern, text, re.IGNORECASE)
    except re.error:
        logger.warning("Invalid P10.split_marker_regex %r; falling back to default", pattern)
        m = re.search(_DEFAULT_SPLIT_MARKER_REGEX, text, re.IGNORECASE)
    if not m:
        return None
    try:
        part_n = int(m.group(1))
        total_n = int(m.group(2))
        if 1 <= part_n <= total_n and 2 <= total_n <= 99:
            return part_n, total_n
    except (ValueError, IndexError):
        return None
    return None


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

    # TASK-35: bank-vs-partition similarity is the only fuzzy gate; in-partition
    # membership is exact on the normalised key. The legacy P6.counterparty_threshold
    # rule is deprecated — it no longer affects matching.
    bank_cp_min  = float(pattern_rule_value(config, "P6", "bank_counterparty_min_similarity", 0.95))
    max_grp_size = int(pattern_rule_value(config, "P6", "max_group_size", 6))
    date_window  = int(pattern_rule_value(config, "P6", "date_window_days", 3))
    var_subpass  = bool(pattern_rule_value(config, "P6", "variance_subpass_enabled", True))
    var_max_size = int(pattern_rule_value(config, "P6", "variance_subpass_max_group_size", 3))
    # TASK-36: bank-side batch markers (e.g. end_to_end_id = "BATCH-GRP-A") seed grouping
    # first and earn a higher confidence (default 92 vs 88 for unflagged subset-sum hits).
    marker_regex      = str(pattern_rule_value(config, "P6", "batch_marker_regex", _DEFAULT_BATCH_MARKER_REGEX))
    marker_confidence = int(pattern_rule_value(config, "P6", "marker_seeded_confidence", 92))

    groups: List[Dict] = []
    used_psr_ids: set = set()
    used_camt_ids: set = set()

    # TASK-35: partition residual PSRs by normalised counterparty key. A P6 group
    # may only contain PSRs from a SINGLE partition — never mix customers.
    partitions: Dict[str, List[PsrTransaction]] = {}
    for p in residual_psrs:
        key = normalise_counterparty(p.counterparty)
        if not key:
            continue
        partitions.setdefault(key, []).append(p)

    # TASK-36: put marker-bearing CAMTs at the head of the queue so they get first
    # refusal on PSRs. Marker is a HINT, not a hard requirement — counterparty
    # partition still has to align, and subset-sum still has to clear.
    marker_camts: List[CamtTransaction] = []
    normal_camts: List[CamtTransaction] = []
    for c in residual_camts:
        if is_bank_batch_marker(c.end_to_end_id, marker_regex):
            marker_camts.append(c)
        else:
            normal_camts.append(c)
    ordered_camts = marker_camts + normal_camts

    for camt in ordered_camts:
        if camt.ntry_id in used_camt_ids or camt.amount is None:
            continue

        bank_key = normalise_counterparty(camt.counterparty)
        if not bank_key:
            continue

        marker_seeded = is_bank_batch_marker(camt.end_to_end_id, marker_regex)

        # Step 1: locate the matching partition for this bank entry.
        # Prefer exact key match; otherwise allow a high-bar fuzzy match
        # (bank_cp_min, default 0.95) on the normalised keys.
        partition_key = None
        if bank_key in partitions:
            partition_key = bank_key
        else:
            best_key, best_sim = None, 0.0
            for k in partitions.keys():
                # Sibling-entity guard: never bind to a partition that differs
                # only in trailing 1-2 alphanumeric chars from the bank key.
                if trailing_single_char_diff(bank_key, k):
                    continue
                sim = similarity(bank_key, k)
                if sim > best_sim:
                    best_key, best_sim = k, sim
            if best_key and best_sim >= bank_cp_min:
                partition_key = best_key

        if not partition_key:
            continue

        # Step 2: narrow to PSRs from that partition only, applying direction + date window.
        candidates = [
            p for p in partitions[partition_key]
            if p.id not in used_psr_ids
            and p.direction == camt.direction
            and safe_date_diff(p.execution_date or "", camt.booking_date or "") <= date_window
        ]
        if len(candidates) < 2:
            continue

        # Step 3: exact subset-sum
        exact_matches = _find_subset_matches(
            candidates, camt.amount, max_grp_size, settings.exact_amount_tolerance
        )
        if exact_matches:
            chosen    = exact_matches[0]
            ambiguous = len(exact_matches) > 1
            alt       = exact_matches[1] if ambiguous else None
            if ambiguous:
                conf, rule, reason = 72, "P6_BANK_BATCH_GROUPING_AMBIGUOUS", "BANK_BATCH_GROUPING_AMBIGUOUS"
            elif marker_seeded:
                conf, rule, reason = marker_confidence, "P6_BANK_BATCH_GROUPING", "BANK_BATCH_GROUPING"
            else:
                conf, rule, reason = 88, "P6_BANK_BATCH_GROUPING", "BANK_BATCH_GROUPING"
            psr_ids_str = ", ".join(p.id for p in chosen)
            marker_prefix = (
                f"Bank flagged this as batch settlement ({camt.end_to_end_id}). "
                if marker_seeded and not ambiguous else ""
            )
            expl = (
                f"{marker_prefix}"
                f"{'Ambiguous: multiple valid groupings. Selected by earliest date. ' if ambiguous else ''}"
                f"{len(chosen)} PSR transactions ({psr_ids_str}) sum to "
                f"{sum(p.amount for p in chosen):.2f} = CAMT {camt.ntry_id} ({camt.amount:.2f}). "
                f"Counterparty partition '{partition_key}' confirmed."
            )
            if ambiguous and alt:
                expl += f" Alternative grouping: {', '.join(p.id for p in alt)}."
            _record_group(groups, used_psr_ids, used_camt_ids, camt, chosen, alt,
                          conf, rule, reason, expl, 0.0, ambiguous)
            continue

        # Step 4: variance sub-pass (small groups only)
        if var_subpass and len(candidates) >= 2:
            var_matches = _find_subset_matches(
                candidates, camt.amount, var_max_size, settings.minor_variance_tolerance
            )
            if var_matches:
                chosen      = var_matches[0]
                group_sum   = sum(p.amount for p in chosen)
                grp_var     = round(group_sum - camt.amount, 2)
                psr_ids_str = ", ".join(p.id for p in chosen)
                marker_prefix = (
                    f"Bank flagged this as batch settlement ({camt.end_to_end_id}). "
                    if marker_seeded else ""
                )
                expl = (
                    f"{marker_prefix}"
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


# ── P10 split-settlement helpers (TASK-38) ─────────────────────────────────────

def _find_camt_subset_matches(
    camts: List[CamtTransaction],
    target: float,
    max_size: int,
    tolerance: float,
) -> List[List[CamtTransaction]]:
    """Return up to 2 CAMT subsets whose amounts sum to target within tolerance.
    Sorted deterministically: earliest booking_date, tiebreak ntry_id asc.
    Stops at 2 results so callers can detect ambiguity without further search."""
    results: List[List[CamtTransaction]] = []
    pool = [c for c in camts if c.amount is not None]
    for size in range(2, min(max_size, len(pool)) + 1):
        for combo in _combinations(pool, size):
            if abs(sum(c.amount for c in combo) - target) <= tolerance:
                sorted_combo = sorted(combo, key=lambda c: (c.booking_date or "", c.ntry_id))
                results.append(list(sorted_combo))
                if len(results) >= 2:
                    return results
        if results:
            return results  # found matches at this size; don't try larger subsets
    return results


def find_one_to_n_splits(
    residual_psrs: List[PsrTransaction],
    residual_camts: List[CamtTransaction],
    config: Dict[str, Dict],
) -> List[Dict]:
    """Find PSRs whose amount is settled by N CAMT entries (split settlement).

    Two trigger paths, evaluated in order so the stronger evidence wins first:
      1. Shared PMT-REF / invoice linkage: 2+ CAMTs whose pmt_ref or invoice
         matches the PSR's reference and whose amounts sum to PSR.amount.
         Confidence 92 (default). 'K of N' marker text in remittance adds
         richer explanation but is not required.
      2. Counterparty subset-sum: CAMTs in the same normalised counterparty
         partition (TASK-35 helper) within ±date_window summing to PSR.amount.
         Confidence 86. Ambiguous if multiple valid subsets — confidence 70.

    Returns a list of split dicts with keys:
        psr, camts (date-sorted), anchor_camt, confidence, rule_applied,
        reason_code, explanation, marker_detected, ambiguous,
        alternative_camts, variance
    """
    if not pattern_is_active(config, "P10"):
        return []

    max_split    = int(pattern_rule_value(config, "P10", "max_split_size", 5))
    date_window  = int(pattern_rule_value(config, "P10", "date_window_days", 3))
    cp_min_sim   = float(pattern_rule_value(config, "P10", "bank_counterparty_min_similarity", 0.95))
    marker_regex = str(pattern_rule_value(config, "P10", "split_marker_regex", _DEFAULT_SPLIT_MARKER_REGEX))
    ref_conf     = int(pattern_rule_value(config, "P10", "shared_reference_confidence", 92))
    sum_conf     = int(pattern_rule_value(config, "P10", "subset_sum_confidence", 86))

    splits: List[Dict] = []
    used_psr_ids: set = set()
    used_camt_ids: set = set()

    # Index residual CAMTs by reference + invoice for Path 1
    camts_by_ref: Dict[str, List[CamtTransaction]] = {}
    camts_by_inv: Dict[str, List[CamtTransaction]] = {}
    for c in residual_camts:
        if c.amount is None:
            continue
        if c.pmt_ref:
            camts_by_ref.setdefault(c.pmt_ref, []).append(c)
        if c.invoice:
            camts_by_inv.setdefault(c.invoice, []).append(c)

    # ── Path 1: shared PMT-REF / invoice linkage ──────────────────────────────
    for psr in residual_psrs:
        if psr.id in used_psr_ids:
            continue

        candidate_buckets: List[Tuple[str, str, List[CamtTransaction]]] = []
        if psr.reference and psr.reference in camts_by_ref:
            bucket = [c for c in camts_by_ref[psr.reference]
                      if c.ntry_id not in used_camt_ids and c.direction == psr.direction]
            if len(bucket) >= 2:
                candidate_buckets.append(("PMT-REF", psr.reference, bucket))
        if psr.invoice and psr.invoice in camts_by_inv:
            bucket = [c for c in camts_by_inv[psr.invoice]
                      if c.ntry_id not in used_camt_ids and c.direction == psr.direction]
            if len(bucket) >= 2:
                candidate_buckets.append(("invoice", psr.invoice, bucket))

        for link_kind, link_value, bucket in candidate_buckets:
            total = round(sum(c.amount for c in bucket), 2)
            if abs(total - psr.amount) <= settings.exact_amount_tolerance and len(bucket) <= max_split:
                chosen = sorted(bucket, key=lambda c: (c.booking_date or "", c.ntry_id))
                ambiguous = False
                alt = None
            else:
                subsets = _find_camt_subset_matches(
                    bucket, psr.amount, max_split, settings.exact_amount_tolerance
                )
                if not subsets:
                    continue
                chosen = subsets[0]
                ambiguous = len(subsets) > 1
                alt = subsets[1] if ambiguous else None

            markers = []
            for c in chosen:
                m = detect_split_marker(c.remittance, marker_regex)
                if m:
                    markers.append((c.ntry_id, m))

            marker_clause = ""
            if markers:
                marker_clause = (
                    f"Bank marked these as split parts ("
                    + ", ".join(f"{cid} = {p}/{t}" for cid, (p, t) in markers)
                    + "). "
                )

            camt_ids_str = ", ".join(c.ntry_id for c in chosen)
            expl = (
                f"{marker_clause}"
                f"{'Ambiguous: multiple valid CAMT subsets. Selected by earliest date. ' if ambiguous else ''}"
                f"PSR {psr.id} ({psr.amount:.2f}) is settled by {len(chosen)} CAMT entries "
                f"({camt_ids_str}) sharing {link_kind} '{link_value}', summing to "
                f"{sum(c.amount for c in chosen):.2f}."
            )
            if ambiguous and alt:
                expl += f" Alternative subset: {', '.join(c.ntry_id for c in alt)}."

            splits.append({
                "psr": psr, "camts": chosen, "anchor_camt": chosen[0],
                "confidence": 70 if ambiguous else ref_conf,
                "rule_applied": "P10_SPLIT_SHARED_REFERENCE_AMBIGUOUS" if ambiguous else "P10_SPLIT_SHARED_REFERENCE",
                "reason_code": "SPLIT_SETTLEMENT_AMBIGUOUS" if ambiguous else "SPLIT_SETTLEMENT_SHARED_REFERENCE",
                "explanation": expl,
                "marker_detected": bool(markers),
                "ambiguous": ambiguous,
                "alternative_camts": alt,
                "variance": round(sum(c.amount for c in chosen) - psr.amount, 2),
            })
            used_psr_ids.add(psr.id)
            for c in chosen:
                used_camt_ids.add(c.ntry_id)
            break  # one split per PSR

    # ── Path 2: counterparty subset-sum (no shared reference required) ────────
    # Partition the still-unmatched CAMTs by normalised counterparty.
    camt_partitions: Dict[str, List[CamtTransaction]] = {}
    for c in residual_camts:
        if c.ntry_id in used_camt_ids or c.amount is None:
            continue
        key = normalise_counterparty(c.counterparty)
        if key:
            camt_partitions.setdefault(key, []).append(c)

    for psr in residual_psrs:
        if psr.id in used_psr_ids:
            continue
        psr_key = normalise_counterparty(psr.counterparty)
        if not psr_key:
            continue

        # Find the matching CAMT partition (exact key first, then high-bar fuzzy)
        target_key = None
        if psr_key in camt_partitions:
            target_key = psr_key
        else:
            best_sim = 0.0
            best_key = None
            for ck in camt_partitions:
                if trailing_single_char_diff(psr_key, ck):
                    continue
                s = similarity(psr_key, ck)
                if s > best_sim:
                    best_sim, best_key = s, ck
            if best_key and best_sim >= cp_min_sim:
                target_key = best_key
        if not target_key:
            continue

        avail = [
            c for c in camt_partitions[target_key]
            if c.ntry_id not in used_camt_ids
            and c.direction == psr.direction
            and safe_date_diff(psr.execution_date or "", c.booking_date or "") <= date_window
        ]
        if len(avail) < 2:
            continue

        subsets = _find_camt_subset_matches(
            avail, psr.amount, max_split, settings.exact_amount_tolerance
        )
        if not subsets:
            continue

        chosen = subsets[0]
        ambiguous = len(subsets) > 1
        alt = subsets[1] if ambiguous else None
        conf = 70 if ambiguous else sum_conf
        rule = "P10_SPLIT_SUBSET_SUM_AMBIGUOUS" if ambiguous else "P10_SPLIT_SUBSET_SUM"
        reason = "SPLIT_SETTLEMENT_AMBIGUOUS" if ambiguous else "SPLIT_SETTLEMENT_SUBSET_SUM"
        camt_ids_str = ", ".join(c.ntry_id for c in chosen)
        expl = (
            f"{'Ambiguous: multiple valid CAMT subsets. Selected by earliest date. ' if ambiguous else ''}"
            f"PSR {psr.id} ({psr.amount:.2f}) is settled by {len(chosen)} CAMT entries "
            f"({camt_ids_str}) summing to {sum(c.amount for c in chosen):.2f}. "
            f"Counterparty partition '{target_key}' confirmed."
        )
        if ambiguous and alt:
            expl += f" Alternative subset: {', '.join(c.ntry_id for c in alt)}."

        splits.append({
            "psr": psr, "camts": chosen, "anchor_camt": chosen[0],
            "confidence": conf, "rule_applied": rule, "reason_code": reason,
            "explanation": expl, "marker_detected": False,
            "ambiguous": ambiguous, "alternative_camts": alt,
            "variance": 0.0,
        })
        used_psr_ids.add(psr.id)
        for c in chosen:
            used_camt_ids.add(c.ntry_id)

    return splits

# ── End P10 helpers ────────────────────────────────────────────────────────────


def reconcile_transactions(psr_transactions: Sequence[PsrTransaction], camt_transactions: Sequence[CamtTransaction], pattern_registry_rows: Sequence[Dict]) -> List[ReconCase]:
    logger.info("reconcile_transactions: psr=%d camt=%d patterns=%d", len(psr_transactions), len(camt_transactions), len(pattern_registry_rows))
    cases=[]; used=set(); idx=1; p5_pending: List[PsrTransaction]=[]
    config = pattern_config(pattern_registry_rows)
    # TASK-37: P4 hardened. similarity_floor replaces threshold (legacy key still honoured).
    _legacy_p4_threshold = pattern_rule_value(config, "P4", "threshold", None)
    if _legacy_p4_threshold is not None:
        logger.warning("P4.threshold is deprecated; use P4.similarity_floor (default 0.92). Legacy value=%s applied as floor.", _legacy_p4_threshold)
        p4_sim_floor = float(_legacy_p4_threshold)
    else:
        p4_sim_floor = float(pattern_rule_value(config, "P4", "similarity_floor", 0.92))
    p4_conf_cap            = int(pattern_rule_value(config, "P4", "confidence_cap", 89))
    p4_corrob_required     = bool(pattern_rule_value(config, "P4", "corroboration_required", True))
    p4_shared_sub_min_len  = int(pattern_rule_value(config, "P4", "shared_substring_min_len", 5))
    p4_date_window_days    = int(pattern_rule_value(config, "P4", "date_window_days", 1))
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
            grp_id    = f"GRP-{idx:06d}"
            camt_b    = grp["camt"]
            psrs_g    = grp["psrs"]   # primary-first (sorted by date/id)
            conf_g    = grp["confidence"]
            rule_g    = grp["rule_applied"]
            reason_g  = grp["reason_code"]
            expl_g    = grp["explanation"]
            grp_var   = grp["group_variance"]
            group_sum = round(sum(p.amount for p in psrs_g), 2)

            if rule_g == "P6_BATCH_MINOR_VARIANCE":
                status_g = "Post to Short or Over Ledger"
            elif rule_g == "P6_BANK_BATCH_GROUPING_AMBIGUOUS":
                status_g = "Suggested Match - Analyst Review"
            else:
                status_g = "Suggested Match - Group Settlement"

            # All PSRs embedded as members — one row per group, not per PSR
            psr_members_g = [
                {"psr_id": p.id, "amount": p.amount,
                 "reference": p.reference or "", "date": p.execution_date or ""}
                for p in psrs_g
            ]
            primary_psr = psrs_g[0]
            days_g = safe_date_diff(primary_psr.execution_date or "", camt_b.booking_date or "")

            feat = {
                "group_id": grp_id, "group_role": "GROUP",
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
                case_id=f"CASE-{idx:06d}", match_key=camt_b.ntry_id,
                psr_id=primary_psr.id, camt_id=camt_b.camt_id,
                reference=primary_psr.reference, invoice=primary_psr.invoice,
                counterparty=primary_psr.counterparty,
                internal_amount=group_sum,
                bank_amount=camt_b.amount,
                variance=round(group_sum - (camt_b.amount or 0), 2),
                currency=primary_psr.currency,
                value_date=primary_psr.execution_date or "", booking_date=camt_b.booking_date or "",
                reconciliation_status=status_g, reason_code=reason_g,
                match_type="N_TO_1", match_confidence=conf_g,
                aging_days=days_g, aging_bucket=aging_bucket(days_g),
                rule_applied=rule_g, exception_flag="Y",
                explanation=expl_g, feature_snapshot=feat, suggestions=sugg_g,
                group_id=grp_id, group_role="GROUP",
                psr_members=psr_members_g,
            )
            cases.append(rc)
            idx += 1

            used.add(camt_b.ntry_id)
            for psr_g in psrs_g:
                p6_consumed_psr_ids.add(psr_g.id)

    # Post-P6 residual: PSRs that did not land in a P6 group
    post_p6_residual = [psr for psr in p5_pending if psr.id not in p6_consumed_psr_ids]

    # ── P10 split-settlement pass (runs AFTER P6, BEFORE P4 — TASK-38) ────────
    # Looks for 1 PSR -> N CAMTs (the inverse of P6's N PSRs -> 1 CAMT). Must run
    # before P4 so a partial-payment PSR isn't fuzzy-matched to one of its CAMTs.
    p10_consumed_psr_ids: set = set()
    p10_splits: List[Dict] = []
    if pattern_is_active(config, "P10") and post_p6_residual:
        residual_camts_for_p10 = [b for b in camt_transactions if b.ntry_id not in used]
        p10_splits = find_one_to_n_splits(post_p6_residual, residual_camts_for_p10, config)

        for split in p10_splits:
            split_id  = f"SPLIT-{idx:06d}"
            psr_s     = split["psr"]
            camts_s   = split["camts"]            # already date-sorted
            conf_s    = split["confidence"]
            rule_s    = split["rule_applied"]
            reason_s  = split["reason_code"]
            expl_s    = split["explanation"]
            ambig_s   = split["ambiguous"]
            camts_sum = round(sum(c.amount for c in camts_s), 2)

            status_s = "Suggested Match - Analyst Review" if ambig_s else "Suggested Match - Split Settlement"

            # All CAMTs embedded as members — one row per split, not per CAMT
            camt_members_s = [
                {"camt_id": c.camt_id, "ntry_id": c.ntry_id,
                 "amount": c.amount, "date": c.booking_date or ""}
                for c in camts_s
            ]
            primary_camt = camts_s[0]
            days_s = safe_date_diff(psr_s.execution_date or "", primary_camt.booking_date or "")

            feat = {
                "split_id": split_id, "group_role": "GROUP",
                "n_camts_in_split": len(camts_s),
                "sum_of_camt_amounts": camts_sum,
                "marker_detected": split["marker_detected"],
                "is_ambiguous": ambig_s,
                "score_breakdown": score_breakdown(
                    {"amount_exact": True, "currency_match": True,
                     "counterparty_similarity": 0.95, "end_to_end_id_exact": False,
                     "pmt_ref_exact": True, "invoice_exact": True,
                     "invoice_suffix_match": False, "amount_variance": 0.0},
                    rule_s, conf_s),
            }
            if ambig_s and split["alternative_camts"]:
                feat["alternative_split_camt_ids"] = [c.ntry_id for c in split["alternative_camts"]]

            sugg_s = [{"action": "CONFIRM_SPLIT_MATCH", "confidence": conf_s / 100.0,
                       "split_id": split_id, "psr_id": psr_s.id,
                       "split_camt_ids": [c.ntry_id for c in camts_s]}]

            rc = ReconCase(
                case_id=f"CASE-{idx:06d}", match_key=psr_s.id,
                psr_id=psr_s.id, camt_id=primary_camt.camt_id,
                reference=psr_s.reference, invoice=psr_s.invoice,
                counterparty=psr_s.counterparty,
                internal_amount=psr_s.amount,
                bank_amount=camts_sum,
                variance=round(camts_sum - psr_s.amount, 2),
                currency=psr_s.currency,
                value_date=psr_s.execution_date or "", booking_date=primary_camt.booking_date or "",
                reconciliation_status=status_s, reason_code=reason_s,
                match_type="1_TO_N", match_confidence=conf_s,
                aging_days=days_s, aging_bucket=aging_bucket(days_s),
                rule_applied=rule_s, exception_flag="Y",
                explanation=expl_s, feature_snapshot=feat, suggestions=sugg_s,
                group_id=split_id, group_role="GROUP",
                camt_members=camt_members_s,
            )
            cases.append(rc)
            idx += 1

            for camt_s in camts_s:
                used.add(camt_s.ntry_id)
            p10_consumed_psr_ids.add(psr_s.id)

    # ── P4 fuzzy 1-to-1 pass (runs AFTER P6 — TASK-34, hardened TASK-37) ───────
    # Lifted out of the per-PSR loop so P6 has first refusal on residuals.
    # P6 uses stronger evidence (subset-sum + counterparty + date window) and should
    # outrank P4 (fuzzy name + amount only). Without this ordering, P4 cannibalises
    # batch members whose individual amount coincidentally matches an unrelated CAMT.
    #
    # TASK-37: P4 now demands BOTH a high similarity floor on normalised keys AND
    # a corroborating signal (shared PMT-REF substring, shared invoice substring,
    # or tight date proximity). Sibling-entity names ("Customer A" vs "Customer B")
    # are blocked by trailing_single_char_diff regardless of score. Confidence is
    # capped (default 89) so the suggestion can never appear auto-closable.
    p4_consumed_psr_ids: set = set()
    if pattern_is_active(config, "P4") and post_p6_residual:
        for psr in post_p6_residual:
            if psr.id in p10_consumed_psr_ids:
                continue
            cands = [b for b in by_amt.get(psr.amount, []) if b.ntry_id not in used]
            if not cands:
                continue
            psr_key = normalise_counterparty(psr.counterparty)
            best_cand: Optional[CamtTransaction] = None
            best_score: float = 0.0
            for b in cands:
                cand_key = normalise_counterparty(b.counterparty)
                if not psr_key or not cand_key:
                    continue
                if trailing_single_char_diff(psr_key, cand_key):
                    continue  # sibling-entity guard — never fuzzy-match A vs B
                sc = similarity(psr_key, cand_key)
                if sc > best_score:
                    best_cand, best_score = b, sc
            if not best_cand or best_score < p4_sim_floor:
                continue

            # Corroboration: a high name score alone is not enough.
            corrob_reasons: List[str] = []
            if shared_substring(psr.reference, best_cand.pmt_ref, p4_shared_sub_min_len):
                corrob_reasons.append(f"shared PMT-REF substring (>={p4_shared_sub_min_len} chars)")
            if shared_substring(psr.invoice, best_cand.invoice, p4_shared_sub_min_len):
                corrob_reasons.append(f"shared invoice substring (>={p4_shared_sub_min_len} chars)")
            date_close = (
                psr.execution_date
                and (best_cand.value_date or best_cand.booking_date)
                and safe_date_diff(psr.execution_date, best_cand.value_date or best_cand.booking_date) <= p4_date_window_days
            )
            if date_close:
                corrob_reasons.append(f"date within +/-{p4_date_window_days} day with exact amount")

            if p4_corrob_required and not corrob_reasons:
                continue  # high similarity but no second signal — defer to P5

            conf = min(int(best_score * 100), p4_conf_cap)
            corrob_text = ("; ".join(corrob_reasons)) if corrob_reasons else "no additional corroboration required (gate disabled)"
            used.add(best_cand.ntry_id)
            cases.append(build_case(
                idx, psr, best_cand, "Suggested Match - Analyst Review",
                "COUNTERPARTY_FUZZY_AMOUNT", "1_TO_1", conf,
                "P4_COUNTERPARTY_FUZZY", "Y",
                f"Counterparty similarity {best_score:.2f} (normalised) with exact amount; "
                f"corroboration: {corrob_text}. Requires analyst confirmation.",
                [{"action": "REVIEW_FUZZY_CANDIDATE", "confidence": round(best_score, 3),
                  "bank_id": best_cand.camt_id, "corroboration": corrob_reasons}],
            ))
            idx += 1
            p4_consumed_psr_ids.add(psr.id)

    # ── P5 exception emission for everything still unmatched ───────────────────
    for psr in post_p6_residual:
        if psr.id in p4_consumed_psr_ids or psr.id in p10_consumed_psr_ids:
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
    logger.info("reconcile_transactions done: %d cases, %d exceptions (p6_groups=%d, p10_splits=%d, p4_matches=%d)",
                len(cases), exceptions, len(p6_groups), len(p10_splits), len(p4_consumed_psr_ids))
    return cases

def case_to_db_tuple(case: ReconCase) -> tuple:
    p=asdict(case)
    return (p["case_id"],p["match_key"],p["psr_id"],p["camt_id"],p["reference"],p["invoice"],p["counterparty"],p["internal_amount"],p["bank_amount"],p["variance"],p["currency"],p["value_date"],p["booking_date"],p["reconciliation_status"],p["reason_code"],p["match_type"],p["match_confidence"],p["aging_days"],p["aging_bucket"],p["rule_applied"],p["exception_flag"],p["explanation"],json.dumps(p["feature_snapshot"]),json.dumps(p["suggestions"]),p["group_id"],p["group_role"],
            json.dumps(p["psr_members"]) if p["psr_members"] is not None else None,
            json.dumps(p["camt_members"]) if p["camt_members"] is not None else None)
