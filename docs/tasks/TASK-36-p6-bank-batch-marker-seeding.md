# TASK-36 · P6 bank-side batch marker seeding

**Type:** Backend
**Branch:** `feat/recon-correctness`
**Depends on:** TASK-35 (uses the normalisation helpers)
**Blocks:** None
**Effort:** ~3–4 hours

---

## Background

Real-world bank statements often label batch settlements explicitly in the end-to-end-id
or remittance fields — for example NTRY-USD-007 in the `abc-recon` sample uses
`end_to_end_id = "BATCH-GRP-A"`. This is a strong hint that:

1. The bank entry is the result of consolidating multiple PSR payments
2. The intended PSR partition is identified by the batch token suffix (`GRP-A`,
   `GRP-B`, etc.) and/or the bank-side debtor name

Today `find_one_to_many_groups()` ignores `camt.end_to_end_id` for group seeding and
relies purely on subset-sum + counterparty filter. When subset-sum is ambiguous (multiple
valid combinations) we fall back to "earliest date" tiebreaker, which is arbitrary. Using
the bank marker as a hint would:

- Make grouping deterministic when the bank tells us which group is which
- Reduce false positives further (combined with TASK-35)
- Give analysts a clearer explanation ("bank explicitly labels this as BATCH-GRP-A")

---

## Acceptance Criteria

- [ ] Configurable regex pattern (default `^(BATCH|BULK|CONSOL|RUN|PAYMENT[-_]?RUN)[-_]`)
      identifies CAMT entries that are batch markers
- [ ] When a CAMT entry's `end_to_end_id` matches the pattern, P6 **prefers** PSR
      partitions whose normalised counterparty matches the bank entry's debtor
- [ ] Explanation text for marker-seeded groups includes the marker token, e.g.
      `Bank flagged this as batch settlement (BATCH-GRP-A). 3 PSRs from "Batch Customer A" sum to 4500.00.`
- [ ] If the marker is present but no PSR partition sums correctly, P6 falls through to
      normal partition + subset-sum logic (the marker is a hint, never a hard requirement)
- [ ] Confidence for marker-seeded groups bumps from 88 → **92** (stronger evidence)
- [ ] `abc-recon` regression:
      - NTRY-USD-007 (`BATCH-GRP-A`) seeds exclusively from "Batch Customer A" PSRs →
        group is `{9007, 9008, 9009}` with confidence 92
      - NTRY-USD-016 (`BATCH-GRP-B`) seeds exclusively from "Batch Customer B" PSRs →
        group is `{9017, 9018}` with confidence 92

---

## Implementation Sketch

1. Add `batch_marker_regex` to pattern_registry config for P6 (default given above).
2. Add helper `is_bank_batch_marker(end_to_end_id: str, pattern: str) -> bool`.
3. In `find_one_to_many_groups()`, iterate CAMTs in two passes:
   - **Pass A — marker-seeded:** for each CAMT where `is_bank_batch_marker(...)`, find the
     matching PSR partition (post-TASK-35 normalisation) and run subset-sum within that
     partition. On hit, emit a marker-seeded group with confidence 92 and the marker token
     in the explanation.
   - **Pass B — generic (existing behaviour):** for remaining CAMTs, run today's
     post-TASK-35 partitioned subset-sum at confidence 88.
4. Both passes share the same `used_psr_ids` / `used_camt_ids` sets to prevent overlap.

---

## Test Plan

- New unit tests in `tests/test_p6_marker_seeding.py`:
  - `test_marker_recognised`: CAMT with `BATCH-GRP-A` end-to-end → marker pass produces a group at confidence 92
  - `test_marker_without_matching_partition`: CAMT with `BATCH-GRP-X` end-to-end where no PSR partition sums → falls through to normal pass; if normal pass also produces nothing, no group emitted
  - `test_marker_with_wrong_counterparty`: CAMT with `BATCH-GRP-A` end-to-end but debtor "Customer Z" — marker hint discarded, falls through (don't trust the regex alone)
  - `test_custom_marker_pattern`: override default regex via pattern_registry → custom pattern recognised
- Extend `abc-recon` regression: assert confidence 92 on the two batch groups
- Run full suite

---

## Risks

- Banks sometimes use end-to-end-id for non-batch purposes (e.g. transaction reference).
  The regex needs to be specific enough to avoid false positives. Default is conservative;
  document that operators should review their bank's actual conventions.
- Some banks put batch markers in `additional_remit_info` or `ustrd` instead of
  `end_to_end_id`. **Out of scope for v1** — capture as backlog item if real data shows it.

---

## Open Questions

1. What batch-marker patterns do real-world banks in your operating regions actually use?
   The default regex needs sanity-checking against actual production CAMT samples.
2. Should the marker token (e.g. `GRP-A`) be persisted to `recon_cases.group_id` instead
   of the synthetic `GRP-000013`? **Recommended: no** — keep synthetic ids for stability,
   but show the bank marker in the explanation and on the EvidenceDrawer sibling panel.

---

## Out of Scope

- Same logic for remittance-field markers (would need parser work)
- Cross-currency batch consolidation
