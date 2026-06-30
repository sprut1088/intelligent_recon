# TASK-40 · P6 — emit one consolidated case per group (N PSR → 1 CAMT)

**Type:** Backend  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** TASK-39 (schema + dataclass)  
**Blocks:** TASK-42, TASK-43, TASK-44  
**Can run in parallel with:** TASK-41  
**Effort:** ~2–3 hours

---

## Background

P6 currently emits one `ReconCase` per PSR in the group (1 ANCHOR + N-1 MEMBERs), causing
case-count inflation and display bugs (anchor shows group sum, not its own PSR amount).

After this task, P6 emits **exactly one case per group**. All PSR details (id, amount,
reference, date) are stored in `psr_members` on that single case. The `group_role` field is
set to `"GROUP"` (not ANCHOR/MEMBER) to distinguish consolidated cases from the old format
during any transition period.

---

## Acceptance Criteria

- [ ] For a group of N PSRs matched to 1 CAMT, exactly **1** `ReconCase` is appended to `cases`
- [ ] `psr_id` on the case holds the primary (first/anchor) PSR ID
- [ ] `internal_amount` = group sum (unchanged — needed for `variance = 0`)
- [ ] `bank_amount` = `camt.amount` (unchanged)
- [ ] `variance` = `group_sum - camt.amount` (unchanged)
- [ ] `psr_members` list contains **all** PSRs in the group (including the primary), each as `{"psr_id", "amount", "reference", "date"}`
- [ ] `group_id` = `GRP-XXXXXX` (unchanged)
- [ ] `group_role` = `"GROUP"` (changed from ANCHOR/MEMBER)
- [ ] No MEMBER rows are emitted — the loop over `enumerate(psrs_g)` is replaced by a single case construction
- [ ] `p6_consumed_psr_ids` still correctly marks all PSRs in the group as consumed
- [ ] `python -m pytest backend/tests/ -v` passes (existing P6 tests will need updating per TASK-45)

---

## Implementation

### Changes to `reconcile_transactions()` in `backend/app/reconciliation.py`

Find the P6 group emission block (the `for pos, psr_g in enumerate(psrs_g):` loop) and
replace the entire loop with a single case construction:

```python
for grp in p6_groups:
    grp_id    = f"GRP-{idx:06d}"
    camt_b    = grp["camt"]
    psrs_g    = grp["psrs"]          # anchor-first order preserved
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

    # Build the members list — all PSRs including the primary
    psr_members = [
        {"psr_id": p.id, "amount": p.amount, "reference": p.reference or "", "date": p.execution_date or ""}
        for p in psrs_g
    ]

    primary_psr = psrs_g[0]
    days_g = safe_date_diff(primary_psr.execution_date or "", camt_b.booking_date or "")

    feat = {
        "group_id": grp_id, "group_role": "GROUP",
        "n_psrs_in_group": len(psrs_g),
        "sum_of_psr_amounts": group_sum,
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
        psr_members=psr_members,
    )
    cases.append(rc)
    idx += 1

    used.add(camt_b.ntry_id)
    for psr_g in psrs_g:
        p6_consumed_psr_ids.add(psr_g.id)
```

Note: `idx` is only incremented **once** per group (not N times). The `used.add(camt_b.ntry_id)` and `p6_consumed_psr_ids` population move outside the old inner loop.
