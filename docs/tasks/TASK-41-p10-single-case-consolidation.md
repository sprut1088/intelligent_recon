# TASK-41 · P10 — emit one consolidated case per split (1 PSR → N CAMT)

**Type:** Backend  
**Branch:** `feat/group-case-consolidation`  
**Depends on:** TASK-39 (schema + dataclass)  
**Blocks:** TASK-42, TASK-43, TASK-44  
**Can run in parallel with:** TASK-40  
**Effort:** ~2–3 hours

---

## Background

P10 (1 PSR → N CAMTs) has the same structural problem as P6 but in the opposite direction:
it emits one `ReconCase` per CAMT (1 ANCHOR + N-1 MEMBERs). This causes:

- Case-count inflation
- Member rows show `internal_amount = None` (the PSR amount is missing from member display)
- The EvidenceDrawer sibling panel does **not render at all** for `1_TO_N` cases
  (the panel only checks `match_type === "N_TO_1"`)
- No badge in ResultTable for `1_TO_N`

After this task, P10 emits **exactly one case per split**. All CAMT details are stored in
`camt_members` on that single case.

---

## Acceptance Criteria

- [ ] For a split of 1 PSR → N CAMTs, exactly **1** `ReconCase` is appended to `cases`
- [ ] `camt_id` on the case holds the primary (first/anchor) CAMT ID
- [ ] `internal_amount` = `psr.amount` (unchanged)
- [ ] `bank_amount` = sum of all split CAMT amounts (unchanged)
- [ ] `variance` = `bank_amount - internal_amount` (unchanged)
- [ ] `camt_members` list contains **all** CAMTs in the split (including the primary), each as `{"camt_id": str, "ntry_id": str, "amount": float, "date": str}`
- [ ] `group_id` = `SPLIT-XXXXXX` (unchanged)
- [ ] `group_role` = `"GROUP"` (changed from ANCHOR/MEMBER)
- [ ] No MEMBER rows are emitted — the loop over `enumerate(camts_s)` is replaced by a single case construction
- [ ] `p10_consumed_psr_ids` and `used` (CAMT ntry_ids) are still populated correctly for all CAMTs in the split
- [ ] `python -m pytest backend/tests/ -v` passes (existing P10 tests will need updating per TASK-45)

---

## Implementation

### Changes to `reconcile_transactions()` in `backend/app/reconciliation.py`

Find the P10 split emission block (the `for pos, camt_s in enumerate(camts_s):` loop) and
replace the entire loop with a single case construction:

```python
for split in p10_splits:
    split_id  = f"SPLIT-{idx:06d}"
    psr_s     = split["psr"]
    camts_s   = split["camts"]          # anchor-first (date-sorted)
    conf_s    = split["confidence"]
    rule_s    = split["rule_applied"]
    reason_s  = split["reason_code"]
    expl_s    = split["explanation"]
    ambig_s   = split["ambiguous"]
    camts_sum = round(sum(c.amount for c in camts_s), 2)

    status_s = "Suggested Match - Analyst Review" if ambig_s else "Suggested Match - Split Settlement"

    # Build the members list — all CAMTs including the primary
    camt_members = [
        {"camt_id": c.camt_id, "ntry_id": c.ntry_id, "amount": c.amount, "date": c.booking_date or ""}
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
        camt_members=camt_members,
    )
    cases.append(rc)
    idx += 1

    # Mark all CAMTs in the split as used
    for camt_s in camts_s:
        used.add(camt_s.ntry_id)
    p10_consumed_psr_ids.add(psr_s.id)
```

Note: `idx` increments once per split. The `used.add()` loop replaces the per-iteration
`used.add(camt_s.ntry_id)` that was inside the old MEMBER case construction.
