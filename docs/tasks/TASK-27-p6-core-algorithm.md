# TASK-27 · P6 Core Algorithm — `find_one_to_many_groups()`

**Type:** Backend  
**Branch:** `feat/one-2-many`  
**Depends on:** TASK-26 (schema + dataclass must exist)  
**Blocks:** TASK-28  
**Effort:** ~3–4 hours

---

## Background

This task implements the core subset-sum algorithm that finds groups of PSR transactions whose
amounts sum to a single CAMT bank entry amount. The function is a pure computation step — it
takes residual pools as input and returns group descriptors without touching the database.

### Design decisions (from design discussions)

- **Direction:** N→1 only (many PSR → one CAMT bank entry)
- **Exact sum first** — subset-sum must equal CAMT amount within `exact_amount_tolerance`
- **Variance sub-pass** — secondary pass for small groups (≤`variance_subpass_max_group_size`)
  allows a gap up to `minor_variance_tolerance` (default €50); confidence drops to 78
- **Ambiguity** — if two or more distinct subsets both satisfy the target, mark as ambiguous,
  pick deterministically (earliest `execution_date`, tiebreak `psr_id` asc), drop confidence to 72
- **Anchor** — first PSR in the sorted chosen subset (earliest date / lowest ID)
- **`internal_amount` on anchor** — stores the **sum** of all group PSR amounts so that
  `variance = internal_amount − bank_amount` stays meaningful
- All config knobs are read from the P6 `pattern_rule_json` via `pattern_rule_value()`

---

## Acceptance Criteria

- [ ] `find_one_to_many_groups()` function added to `backend/app/reconciliation.py`
- [ ] Returns a list of group dicts (schema defined below)
- [ ] Each CAMT can appear in at most one group (first match wins, earlier CAMTs take priority)
- [ ] Each PSR can appear in at most one group
- [ ] Exact-sum unambiguous → confidence 88, `rule_applied = "P6_BANK_BATCH_GROUPING"`
- [ ] Exact-sum ambiguous → confidence 72, `rule_applied = "P6_BANK_BATCH_GROUPING_AMBIGUOUS"`
- [ ] Variance sub-pass hit → confidence 78, `rule_applied = "P6_BATCH_MINOR_VARIANCE"`
- [ ] Config knobs respected: `max_group_size`, `date_window_days`, `counterparty_threshold`,
      `variance_subpass_enabled`, `variance_subpass_max_group_size`
- [ ] Function is pure (no DB access, no side effects)
- [ ] Unit-testable in isolation with synthetic fixtures

---

## Implementation

Add the following to `backend/app/reconciliation.py`, after the `similarity()` function
and before `reconcile_transactions()`.

### Helper — `_find_subset_matches()`

```python
from itertools import combinations as _combinations

def _find_subset_matches(
    psrs: List[PsrTransaction],
    target: float,
    max_size: int,
    tolerance: float,
) -> List[List[PsrTransaction]]:
    """Return up to 2 sorted PSR subsets whose sum equals target within tolerance.
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
```

### Main function — `find_one_to_many_groups()`

```python
def find_one_to_many_groups(
    residual_psrs: List[PsrTransaction],
    residual_camts: List[CamtTransaction],
    config: Dict[str, Dict],
) -> List[Dict]:
    """Find groups of PSR transactions whose amounts sum to a single CAMT entry.

    Returns a list of group dicts with keys:
        camt          — CamtTransaction (the bank entry)
        psrs          — List[PsrTransaction] sorted anchor-first (earliest date / lowest id)
        anchor_psr    — PsrTransaction (first item in psrs; owns the group)
        confidence    — int (88 exact / 78 variance / 72 ambiguous)
        rule_applied  — str
        reason_code   — str
        explanation   — str
        ambiguous     — bool
        group_variance — float (sum of PSR amounts − bank_amount; 0.0 for exact matches)
        alternative_psrs — Optional[List[PsrTransaction]] (non-None when ambiguous)
    """
    if not pattern_is_active(config, "P6"):
        return []

    cp_threshold  = float(pattern_rule_value(config, "P6", "counterparty_threshold", 0.85))
    max_grp_size  = int(pattern_rule_value(config, "P6", "max_group_size", 6))
    date_window   = int(pattern_rule_value(config, "P6", "date_window_days", 3))
    var_subpass   = bool(pattern_rule_value(config, "P6", "variance_subpass_enabled", True))
    var_max_size  = int(pattern_rule_value(config, "P6", "variance_subpass_max_group_size", 3))

    groups: List[Dict] = []
    used_psr_ids: set = set()   # PSRs claimed by earlier groups in this call
    used_camt_ids: set = set()  # CAMTs claimed by earlier groups

    for camt in residual_camts:
        if camt.ntry_id in used_camt_ids:
            continue
        if camt.amount is None:
            continue

        # --- Step 1: narrow PSR pool ---
        candidates = [
            p for p in residual_psrs
            if p.id not in used_psr_ids
            and p.direction == camt.direction
            and similarity(p.counterparty, camt.counterparty) >= cp_threshold
            and safe_date_diff(p.execution_date or "", camt.booking_date or "") <= date_window
        ]
        if len(candidates) < 2:
            continue  # need at least 2 PSRs to form a group

        # --- Step 2: exact subset-sum ---
        exact_matches = _find_subset_matches(
            candidates, camt.amount, max_grp_size, settings.exact_amount_tolerance
        )

        if exact_matches:
            chosen = exact_matches[0]
            ambiguous = len(exact_matches) > 1
            alternative = exact_matches[1] if ambiguous else None

            confidence  = 72 if ambiguous else 88
            rule        = "P6_BANK_BATCH_GROUPING_AMBIGUOUS" if ambiguous else "P6_BANK_BATCH_GROUPING"
            reason      = "BANK_BATCH_GROUPING_AMBIGUOUS"    if ambiguous else "BANK_BATCH_GROUPING"
            psr_ids_str = ", ".join(p.id for p in chosen)
            expl = (
                f"{'Ambiguous: multiple valid groupings. Selected by earliest date. ' if ambiguous else ''}"
                f"{len(chosen)} PSR transactions ({psr_ids_str}) sum to "
                f"{sum(p.amount for p in chosen):.2f} = CAMT {camt.ntry_id} "
                f"({camt.amount:.2f}). Counterparty similarity confirmed."
            )
            if ambiguous and alternative:
                alt_ids = ", ".join(p.id for p in alternative)
                expl += f" Alternative grouping: {alt_ids}."

            _record_group(groups, used_psr_ids, used_camt_ids, camt, chosen, alternative,
                          confidence, rule, reason, expl, 0.0, ambiguous)
            continue

        # --- Step 3: variance sub-pass (small groups only) ---
        if var_subpass and len(candidates) >= 2:
            var_matches = _find_subset_matches(
                candidates, camt.amount, var_max_size, settings.minor_variance_tolerance
            )
            if var_matches:
                chosen      = var_matches[0]
                group_sum   = sum(p.amount for p in chosen)
                grp_variance = round(group_sum - camt.amount, 2)
                psr_ids_str = ", ".join(p.id for p in chosen)
                expl = (
                    f"{len(chosen)} PSR transactions ({psr_ids_str}) sum to "
                    f"{group_sum:.2f} vs CAMT {camt.ntry_id} ({camt.amount:.2f}). "
                    f"Variance {grp_variance:+.2f} is within minor tolerance. "
                    f"Post to short/over ledger."
                )
                _record_group(groups, used_psr_ids, used_camt_ids, camt, chosen, None,
                              78, "P6_BATCH_MINOR_VARIANCE", "AMOUNT_VARIANCE_MINOR_BATCH",
                              expl, grp_variance, False)

    return groups


def _record_group(
    groups: List[Dict],
    used_psr_ids: set,
    used_camt_ids: set,
    camt: "CamtTransaction",
    chosen: List["PsrTransaction"],
    alternative: Optional[List["PsrTransaction"]],
    confidence: int,
    rule_applied: str,
    reason_code: str,
    explanation: str,
    group_variance: float,
    ambiguous: bool,
) -> None:
    """Mutates used sets and appends to groups list."""
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
```

---

## Verification

```bash
cd backend
python -c "
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import find_one_to_many_groups, pattern_config
import json

# Minimal fake patterns list
patterns = [{
    'pattern_id': 'P6', 'pattern_name': 'One-to-Many Bank Settlement',
    'pattern_type': 'SEED', 'status': 'ACTIVE', 'execution_mode': 'SUGGESTION',
    'confidence_threshold': 0.85,
    'pattern_rule_json': json.dumps({
        'counterparty_threshold': 0.85, 'max_group_size': 6,
        'date_window_days': 3, 'variance_subpass_enabled': True,
        'variance_subpass_max_group_size': 3
    })
}]
config = pattern_config(patterns)

psrs = [
    PsrTransaction('TX-001', '2026-06-01', 'PMT-REF-001', 300.0, 'CR', 'INV-001', 'Crestwood Retail', 'EUR', 1, ''),
    PsrTransaction('TX-002', '2026-06-01', 'PMT-REF-002', 400.0, 'CR', 'INV-002', 'Crestwood Retail', 'EUR', 2, ''),
    PsrTransaction('TX-003', '2026-06-01', 'PMT-REF-003', 300.0, 'CR', 'INV-003', 'Crestwood Retail', 'EUR', 3, ''),
]
camts = [
    CamtTransaction('NTRY-001', 'NTRY-001', '', 700.0, 'CR', '2026-06-01', '2026-06-01', 'EUR', 'batch payment', 'Crestwood Retail', '', '', {}),
]

groups = find_one_to_many_groups(psrs, camts, config)
assert len(groups) == 1, f'Expected 1 group, got {len(groups)}'
g = groups[0]
assert g['confidence'] == 88, f'Expected 88, got {g[\"confidence\"]}'
assert len(g['psrs']) == 2, f'Expected 2 PSRs, got {len(g[\"psrs\"])}'
assert sum(p.amount for p in g['psrs']) == 700.0
print('find_one_to_many_groups: OK')
"
```
