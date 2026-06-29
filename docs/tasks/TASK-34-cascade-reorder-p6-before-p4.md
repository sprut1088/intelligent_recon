# TASK-34 · Cascade re-order — P6 before P4

**Type:** Backend
**Branch:** `feat/recon-correctness`
**Depends on:** None
**Blocks:** TASK-35, TASK-36 should land on the re-ordered cascade
**Effort:** ~1–2 hours

---

## Background

Today's cascade in `reconciliation.py → reconcile_transactions()` runs **per-PSR** in this
order: P1 → P2 → P3 → P3+P7 → learned (P8) → **P4** → fallback to `p5_pending`.
P6 (one-to-many batch grouping) only sees PSRs that landed in `p5_pending`.

This causes a confirmed defect (see `abc-recon` regression):

- TX-2026-9009 (Batch Customer A, 2000 USD, member of BATCH-GRP-A) was matched **1-to-1 by
  P4** to NTRY-USD-016 (Batch Customer **B**, 2000 USD) because "Batch Customer A" vs
  "Batch Customer B" yields fuzzy similarity ≈ 0.94, above the 0.85 P4 threshold, and the
  amounts coincidentally match.
- By the time P6 ran, TX-9009 was no longer in `p5_pending`, so the correct batch group
  (9007 + 9008 + 9009 → NTRY-USD-007) could not form.

The structural fix is to give P6 first refusal on residuals before P4 fires. P6 uses
**stronger** evidence (subset-sum + same-customer + same-direction + date window) and
should outrank P4 (fuzzy + amount only).

---

## Acceptance Criteria

- [ ] All PSRs that fail P1/P2/P3/P3+P7/P8 are staged into `p5_pending` **without** being
      tested by P4 in the same loop iteration
- [ ] P6 runs on `p5_pending` first
- [ ] A **post-P6 P4 pass** runs on the PSRs that P6 left behind (i.e. those still
      unmatched after P6 consumed batch members)
- [ ] P5 (exception emission) runs last on the final residual
- [ ] All existing tests still pass (`backend/tests/`)
- [ ] `abc-recon` regression: case for TX-9009 no longer surfaces as a P4 match; it appears
      as a MEMBER of the GRP-A group (assuming TASK-35 still pending — partial credit, full
      fix lands with TASK-35)

---

## Implementation Sketch

In `backend/app/reconciliation.py → reconcile_transactions()`:

1. Inside the per-PSR loop, **remove** the P4 block (lines around 327–333). PSRs that
   reach that point should fall straight into `p5_pending`.
2. After the existing P6 block finishes, add a **second pass over `p5_pending` minus
   P6-consumed PSRs** that applies the same P4 logic the per-PSR loop used to run:
   - Re-derive the `by_amt` index from `camt_transactions` filtered by `b.ntry_id not in used`
   - For each remaining PSR, find best fuzzy candidate by counterparty + amount
   - If `score >= p4_threshold`, emit a P4 case exactly as before
3. The final P5 emission loop runs on whatever is still unmatched after the new P4 pass.

**Note:** there is also a "learned pattern" (P8) block before P4 in the per-PSR loop. Leave
P8 where it is — learned suggestions are already gated by analyst approval and should not
be deferred. Only P4 moves.

---

## Test Plan

- Run full suite: `python -m pytest backend/tests/ -v`
- **New regression test** — add `tests/test_cascade_order.py`:
  - Build fixture with one PSR that has no end-to-end / PMT-REF / invoice match but whose
    counterparty is fuzzy-similar to an unrelated CAMT entry with the same amount, AND
    also belongs to a valid 3-PSR group summing to a different CAMT entry
  - Assert: the PSR appears as a P6 group MEMBER, not as a P4 1-to-1 match
- Pre-existing test `test_pattern_config.py PX-TEST 409` failure is unrelated and may
  remain (already known).

---

## Risks

- Some existing P4-expectation tests may have implicitly relied on per-PSR ordering. If a
  test asserts a P4 outcome for a PSR that ALSO has valid P6 grouping, that test was
  testing wrong behaviour and needs updating (call it out in the PR description).
- Performance: the new P4 pass operates on a smaller set (post-P6 residual), so net
  runtime should improve, not degrade.

---

## Out of Scope

- P4 threshold/algorithm changes → TASK-37
- P6 counterparty gate tightening → TASK-35
- Bank-side batch marker hints → TASK-36
- New split-settlement algorithm → TASK-38
