# TASK-28 · Wire P6 into `reconcile_transactions()` cascade

**Type:** Backend  
**Branch:** `feat/one-2-many`  
**Depends on:** TASK-27 (`find_one_to_many_groups()` must exist)  
**Blocks:** TASK-29, TASK-31, TASK-32  
**Effort:** ~3–4 hours

---

## Background

Currently `reconcile_transactions()` processes each PSR transaction in a single pass.
Unmatched PSRs are immediately appended as P5 "Uncleared / In-Transit" cases at the bottom
of the loop, and then leftover CAMT entries become "Bank-only Item" cases.

P6 needs a **residual-pool pass** that runs:
- After the P1–P8 single-match loop
- Before the P5 and bank-only fallback cases are emitted

The refactor collects unmatched PSRs in a staging list instead of immediately appending P5
cases, then runs P6 on the residual pools, then emits remaining P5 and bank-only cases.

---

## Acceptance Criteria

- [ ] P6 pass runs between the P1–P8 loop and the fallback case emission
- [ ] PSRs consumed by P6 do **not** also appear as P5 "Uncleared / In-Transit" cases
- [ ] CAMTs consumed by P6 do **not** also appear as "Bank-only Item" cases
- [ ] Each P6 group produces exactly one ANCHOR case and N−1 MEMBER cases
- [ ] Anchor row: `internal_amount = sum(group PSR amounts)`, `bank_amount = camt.amount`,
      `variance = sum − bank_amount`, `group_role = "ANCHOR"`, `match_type = "N_TO_1"`,
      `suggestions` contains a `CONFIRM_GROUP_MATCH` action
- [ ] Member rows: `internal_amount = this PSR's amount`, `bank_amount = None`,
      `variance = None`, `group_role = "MEMBER"`, `match_type = "N_TO_1"`,
      `suggestions = []`, `feature_snapshot = {"group_member": True, "group_id": ..., "anchor_case_id": ...}`
- [ ] `group_id` is shared across all rows in the group (`GRP-{idx:06d}`)
- [ ] Aging (`aging_days`, `aging_bucket`) computed per-PSR against the shared CAMT `booking_date`
- [ ] Variance sub-pass groups (`P6_BATCH_MINOR_VARIANCE`) produce status
      `"Post to Short or Over Ledger"` on the anchor; members share the same status
- [ ] `exception_flag = "Y"` on all P6 rows (all are suggestions, not auto-close)
- [ ] Existing P1–P8 test cases unaffected
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions

---

## Implementation

### Step 1 — Refactor the P5 fallback in `reconcile_transactions()`

Currently the main PSR loop ends with:
```python
        cases.append(build_case(idx, psr, None, "Uncleared / In-Transit Payment", ...))
        idx += 1
```

Replace that terminal `cases.append(...)` with a staging append:
```python
        p5_pending.append(psr)   # staged — may be consumed by P6
```

And initialise `p5_pending` at the top of `reconcile_transactions()`:
```python
    cases=[]; used=set(); idx=1
    p5_pending: List[PsrTransaction] = []    # ← add this line
```

### Step 2 — Add the P6 residual-pool pass after the PSR loop

Insert the following block between the PSR loop and the existing bank-only loop:

```python
    # ── P6 One-to-Many residual-pool pass ─────────────────────────────────
    if pattern_is_active(config, "P6") and p5_pending:
        residual_camts = [b for b in camt_transactions if b.ntry_id not in used]
        p6_groups = find_one_to_many_groups(p5_pending, residual_camts, config)

        # Track which PSRs and CAMTs P6 has consumed
        p6_consumed_psr_ids: set = set()
        p6_consumed_camt_ids: set = set()

        for group_num, grp in enumerate(p6_groups, start=1):
            grp_id = f"GRP-{idx:06d}"          # use current idx counter for uniqueness
            camt   = grp["camt"]
            psrs   = grp["psrs"]               # anchor-first (sorted by date / id)
            conf   = grp["confidence"]
            rule   = grp["rule_applied"]
            reason = grp["reason_code"]
            expl   = grp["explanation"]
            grp_var = grp["group_variance"]
            group_sum = sum(p.amount for p in psrs)

            # Derive status from rule
            if rule == "P6_BATCH_MINOR_VARIANCE":
                status = "Post to Short or Over Ledger"
            elif rule == "P6_BANK_BATCH_GROUPING_AMBIGUOUS":
                status = "Suggested Match - Analyst Review"
            else:
                status = "Suggested Match - Group Settlement"

            anchor_case_id = f"CASE-{idx:06d}"

            for pos, psr in enumerate(psrs):
                is_anchor = (pos == 0)
                this_case_id = f"CASE-{idx:06d}"

                if is_anchor:
                    # Anchor: internal_amount = group sum (so variance formula works)
                    feature_map = {
                        "group_id": grp_id,
                        "group_role": "ANCHOR",
                        "n_psrs_in_group": len(psrs),
                        "sum_of_psr_amounts": group_sum,
                        "counterparty_consensus_similarity": round(
                            sum(similarity(p.counterparty, camt.counterparty) for p in psrs) / len(psrs), 4
                        ),
                        "max_date_spread_days": max(
                            safe_date_diff(p.execution_date or "", camt.booking_date or "") for p in psrs
                        ),
                        "is_ambiguous": grp["ambiguous"],
                        "group_variance": grp_var,
                        "score_breakdown": score_breakdown(
                            {"amount_exact": grp_var == 0.0, "currency_match": True,
                             "counterparty_similarity": 0.9, "end_to_end_id_exact": False,
                             "pmt_ref_exact": False, "invoice_exact": False,
                             "invoice_suffix_match": False, "amount_variance": grp_var},
                            rule, conf,
                        ),
                    }
                    if grp["ambiguous"] and grp["alternative_psrs"]:
                        feature_map["alternative_group_psr_ids"] = [p.id for p in grp["alternative_psrs"]]

                    suggestions = [{
                        "action": "CONFIRM_GROUP_MATCH",
                        "confidence": conf / 100.0,
                        "group_id": grp_id,
                        "group_psr_ids": [p.id for p in psrs],
                        "camt_id": camt.camt_id,
                    }]

                    days = safe_date_diff(psr.execution_date or "", camt.booking_date or "")
                    rc = ReconCase(
                        case_id=this_case_id,
                        match_key=camt.ntry_id,
                        psr_id=psr.id,
                        camt_id=camt.camt_id,
                        reference=psr.reference,
                        invoice=psr.invoice,
                        counterparty=psr.counterparty,
                        internal_amount=round(group_sum, 2),  # GROUP SUM on anchor
                        bank_amount=camt.amount,
                        variance=round(group_sum - camt.amount, 2),
                        currency=psr.currency,
                        value_date=psr.execution_date or "",
                        booking_date=camt.booking_date or "",
                        reconciliation_status=status,
                        reason_code=reason,
                        match_type="N_TO_1",
                        match_confidence=conf,
                        aging_days=days,
                        aging_bucket=aging_bucket(days),
                        rule_applied=rule,
                        exception_flag="Y",
                        explanation=expl,
                        feature_snapshot=feature_map,
                        suggestions=suggestions,
                        group_id=grp_id,
                        group_role="ANCHOR",
                    )
                else:
                    # Member: own PSR amount, null bank/variance, minimal snapshot
                    feature_map = {
                        "group_member": True,
                        "group_id": grp_id,
                        "anchor_case_id": anchor_case_id,
                    }
                    member_expl = (
                        f"Part of group {grp_id} ({len(psrs)} PSRs sum to "
                        f"{group_sum:.2f} = CAMT {camt.ntry_id} {camt.amount:.2f}). "
                        f"See anchor case {anchor_case_id}."
                    )
                    days = safe_date_diff(psr.execution_date or "", camt.booking_date or "")
                    rc = ReconCase(
                        case_id=this_case_id,
                        match_key=camt.ntry_id,
                        psr_id=psr.id,
                        camt_id=camt.camt_id,
                        reference=psr.reference,
                        invoice=psr.invoice,
                        counterparty=psr.counterparty,
                        internal_amount=psr.amount,    # individual PSR amount on members
                        bank_amount=None,
                        variance=None,
                        currency=psr.currency,
                        value_date=psr.execution_date or "",
                        booking_date=camt.booking_date or "",
                        reconciliation_status=status,
                        reason_code=reason,
                        match_type="N_TO_1",
                        match_confidence=conf,
                        aging_days=days,
                        aging_bucket=aging_bucket(days),
                        rule_applied=rule,
                        exception_flag="Y",
                        explanation=member_expl,
                        feature_snapshot=feature_map,
                        suggestions=[],
                        group_id=grp_id,
                        group_role="MEMBER",
                    )

                cases.append(rc)
                idx += 1
                p6_consumed_psr_ids.add(psr.id)

            p6_consumed_camt_ids.add(camt.ntry_id)
            used.add(camt.ntry_id)  # prevent bank-only fallback for this CAMT

        # Remaining unmatched PSRs → P5 (those not consumed by P6)
        for psr in p5_pending:
            if psr.id in p6_consumed_psr_ids:
                continue
            cases.append(build_case(idx, psr, None, "Uncleared / In-Transit Payment",
                "NO_ACCEPTABLE_CANDIDATES", "UNMATCHED_PSR", 45, "P5_EXCEPTION_HANDLING", "Y",
                "No acceptable bank candidate was found. Route to exception queue and monitor next CAMT cycle.",
                [{"action": "ROUTE_TO_EXCEPTION_QUEUE", "confidence": 0.45,
                  "expected_clear_days": settings.in_transit_days}]))
            idx += 1
    else:
        # P6 disabled or no pending PSRs — emit all as P5
        for psr in p5_pending:
            cases.append(build_case(idx, psr, None, "Uncleared / In-Transit Payment",
                "NO_ACCEPTABLE_CANDIDATES", "UNMATCHED_PSR", 45, "P5_EXCEPTION_HANDLING", "Y",
                "No acceptable bank candidate was found. Route to exception queue and monitor next CAMT cycle.",
                [{"action": "ROUTE_TO_EXCEPTION_QUEUE", "confidence": 0.45,
                  "expected_clear_days": settings.in_transit_days}]))
            idx += 1
    # ── End P6 pass ────────────────────────────────────────────────────────
```

### Step 3 — Verify the bank-only loop uses the updated `used` set

The existing bank-only loop at the bottom of `reconcile_transactions()` already uses:
```python
    for bank in camt_transactions:
        if bank.ntry_id in used: continue
```

Because `used.add(camt.ntry_id)` is called for each P6-consumed CAMT in Step 2, no change is
needed here. Verify this is still the case after the refactor.

---

## Verification

```bash
cd backend
# Smoke test — load sample data and check P6 cases appear when sample has groups
python -c "
from app.loader import load_samples_and_reconcile
result = load_samples_and_reconcile(reset=True)
print('Cases loaded:', result['case_count'])

from app.db import get_conn, rows_to_dicts
with get_conn() as conn:
    p6 = rows_to_dicts(conn.execute(
        \"SELECT * FROM recon_cases WHERE match_type='N_TO_1'\").fetchall())
    p5 = rows_to_dicts(conn.execute(
        \"SELECT * FROM recon_cases WHERE rule_applied='P5_EXCEPTION_HANDLING' AND match_type='UNMATCHED_PSR'\").fetchall())
    print(f'P6 N_TO_1 cases: {len(p6)}')
    print(f'P5 unmatched PSR cases: {len(p5)}')
    if p6:
        anchors = [c for c in p6 if c.get('group_role') == 'ANCHOR']
        members = [c for c in p6 if c.get('group_role') == 'MEMBER']
        print(f'  Anchors: {len(anchors)}, Members: {len(members)}')
        a = anchors[0]
        print(f'  First anchor: {a[\"case_id\"]} group_id={a[\"group_id\"]} conf={a[\"match_confidence\"]}')
"

python -m pytest backend/tests/ -v
```
