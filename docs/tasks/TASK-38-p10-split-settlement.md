# TASK-38 · P10 — Split Settlement (1 PSR → N CAMT)

**Type:** Backend (+ minor frontend reuse)
**Branch:** `feat/p10-split-settlement`
**Depends on:** TASK-34 (must land first so the new algorithm doesn't fight P4)
**Blocks:** Nothing
**Effort:** ~6–8 hours

---

## Background

Today the engine supports `N PSRs → 1 CAMT` via P6 (batch consolidation), but the inverse
is unsupported: `1 PSR → N CAMTs` (split settlement / partial instalments). The
`abc-recon` regression shows the gap clearly:

- PSR TX-2026-9010 (3300 USD, Partial Payer LLC, INV-3010, PMT-REF-91010) is paid in two
  bank entries: NTRY-USD-008 (2000) and NTRY-USD-009 (1300). The bank even labels them
  `1-of-2` / `2-of-2` in remittance.
- Engine outcome today: 1 unmatched PSR (CASE-000018) + 2 bank-only items
  (CASE-000020, CASE-000021) → triple-counted in the exception queue.

The "P10 honesty fix" (TASK-30, already done) made the engine stop pretending it
supported this. This task implements it properly.

---

## Acceptance Criteria

- [ ] New `find_one_to_n_splits()` function in `reconciliation.py`, modelled on
      `find_one_to_many_groups()` but inverted
- [ ] Runs in `reconcile_transactions()` **after P6** and **before the new P4 pass** from
      TASK-34
- [ ] Two trigger paths, evaluated in this order:
  1. **Bank-side marker:** any pair/sequence of CAMT entries whose remittance fields
     contain `\b(\d+)[- _]?(of|/)[- _]?(\d+)\b` referencing the same PSR PMT-REF or
     invoice → group those CAMTs together
  2. **Subset-sum on CAMT side:** for an unmatched PSR with `psr.amount = X`, find K
     unmatched CAMT entries (`2 ≤ K ≤ max_split_size`) with same counterparty within
     `±date_window_days` whose amounts sum to `X` (within `exact_amount_tolerance`)
- [ ] Emits N cases with `match_type = "1_TO_N"`, `group_id = "SPLIT-<id>"`,
      `group_role = "ANCHOR"` on the PSR's case (first chronologically by CAMT
      booking_date) and `MEMBER` on the rest
- [ ] Confidence:
      - 92 for marker-triggered splits
      - 86 for subset-sum splits with no marker
      - Both default to status `"Suggested Match - Split Settlement"` (review-required)
- [ ] Reuses the existing frontend group UI (TASK-31) — the EvidenceDrawer sibling panel
      should render N split CAMTs against the one PSR with no new components needed
- [ ] Resolving the anchor case marks all member cases resolved (group-aware resolve from
      TASK-29 already handles this)
- [ ] `abc-recon` regression:
      - TX-9010 forms one `1_TO_N` group with NTRY-USD-008 + NTRY-USD-009 at confidence 92
        (bank marker present)
      - CASE-000018, CASE-000020, CASE-000021 no longer appear (replaced by the split
        group)

---

## Implementation Sketch

1. Add `find_one_to_n_splits(residual_psrs, residual_camts, config)` to
   `reconciliation.py`. Returns list of dicts:
   ```
   {"psr": <PsrTransaction>, "camts": [<CamtTransaction>, ...],
    "anchor_camt": <CamtTransaction>, "confidence": int,
    "rule_applied": str, "reason_code": str, "explanation": str,
    "marker_detected": bool, "variance": float}
   ```
2. Inside the function:
   - **Path 1 — marker:** scan residual CAMTs for remittance patterns matching the regex.
     Group CAMTs whose marker references the same identifier (PMT-REF, invoice, or PSR
     id). Look up the matching PSR among `residual_psrs`. If amount matches sum, emit
     marker-triggered group.
   - **Path 2 — subset-sum:** for each unmatched PSR, partition residual CAMTs by
     normalised counterparty (reuse TASK-35 helper). Within the matching partition,
     subset-sum target = `psr.amount`. If a unique subset found, emit. If multiple subsets
     found, emit as ambiguous (lower confidence 70).
3. Wire into `reconcile_transactions()` between the P6 block and the new P4 pass.
4. Schema: `recon_cases.match_type` enum already accepts string values — `"1_TO_N"` is
   simply a new value. No migration needed beyond adding it to the validation list if one
   exists. `group_role` already supports ANCHOR/MEMBER from P6.
5. Frontend audit: confirm `App.jsx` group badge logic treats `1_TO_N` the same as
   `N_TO_1` for purposes of showing the group panel. If it filters by exact match, widen
   to `match_type.endsWith('_TO_N') || match_type === 'N_TO_1'`.

---

## Test Plan

- New tests in `tests/test_p10_split_settlement.py`:
  - `test_split_with_bank_marker`: 1 PSR (3300) + 2 CAMTs (2000 with "1-of-2", 1300 with "2-of-2") → one 1_TO_N group at confidence 92
  - `test_split_without_marker_via_subset_sum`: same data without markers → one 1_TO_N group at confidence 86, same counterparty required
  - `test_split_blocked_by_different_counterparty`: 1 PSR (3300) + 2 CAMTs same total but different debtor names → no split, all three go to exception queue
  - `test_split_ambiguous_multiple_subsets`: PSR amount matches multiple valid CAMT pairs → ambiguous group at confidence 70 (or no group emitted — design decision, document chosen behaviour)
  - `test_split_respects_date_window`: CAMTs >N days from PSR execution_date excluded
  - `test_split_max_size_cap`: amount equals sum of 8 small CAMTs but max_split_size=5 → no split
- Extend abc-recon regression: assert the 1_TO_N group exists and the three old cases are gone
- Run full suite

---

## Risks

- Subset-sum explodes combinatorially. Caps are essential:
  - Only consider CAMTs unmatched after all other tiers (small set in practice)
  - `max_split_size` default 5
  - `date_window_days` default 3
  - Bail early if `len(candidate_camts) > 20` (configurable)
- Bank remittance marker patterns vary wildly. Default regex covers `1 of 2`, `1/2`,
  `1-of-2`, `PART 1`, `INSTALMENT 1 of 2`. Document as a config knob.
- Audit/learning: a split group is conceptually one resolution but produces N rows. The
  learning loop (`learning.py`) treats each row independently — confirm whether split
  resolutions should feed back as `learning_eligible = 0` like P6 groups do.

---

## Open Questions

1. When subset-sum finds multiple valid subsets, do we emit an ambiguous group (analyst
   picks) or refuse to suggest (analyst handles manually)? **Recommended: emit ambiguous
   at low confidence (70)**, consistent with P6's `P6_BANK_BATCH_GROUPING_AMBIGUOUS`.
2. Should partial splits (PSR = sum of K CAMTs but a few CAMTs are still missing) be
   detected? **Out of scope for v1** — would require open-invoice ledger tracking.
3. Are cross-currency splits realistic (PSR in USD, CAMTs partly in USD partly converted)?
   **Out of scope for v1** — currency conversion is not in the engine's remit yet.

---

## Out of Scope

- M PSRs → N CAMTs (many-to-many) — separate future task
- Partial-payment lifecycle tracking (open balance carry-forward)
- Currency conversion / multi-currency splits
