# TASK-35 · P6 strict counterparty partitioning

**Type:** Backend
**Branch:** `feat/recon-correctness`
**Depends on:** TASK-34
**Blocks:** None (TASK-36 builds on this but doesn't require it strictly)
**Effort:** ~3–4 hours

---

## Background

`find_one_to_many_groups()` in `reconciliation.py` (line ~199) currently filters PSR
candidates by `similarity(p.counterparty, camt.counterparty) >= cp_threshold` where the
default `cp_threshold` is **0.85**.

That threshold is too loose for the partitioning step. In the `abc-recon` regression:

- NTRY-USD-007 has debtor "Batch Customer A"
- Candidate PSRs include "Batch Customer A" PSRs (sim=1.0) AND "Batch Customer B" PSRs
  (sim≈0.93) — both above 0.85
- Subset-sum then finds `{9007, 9008, 9017, 9018} = 4500`, mixing two distinct customers
  into one batch group

The fix is **partition first, sum second**: PSRs must be partitioned by a strict
counterparty identity, and subset-sum may only consider PSRs from one partition.

---

## Acceptance Criteria

- [ ] `find_one_to_many_groups()` partitions residual PSRs by **normalised counterparty
      key** before running subset-sum
- [ ] Normalisation rules (initial cut, configurable later):
      - Lowercase
      - Strip surrounding whitespace
      - Strip common legal suffixes: `llc`, `inc`, `co`, `corp`, `ltd`, `gmbh`, `pvt`,
        `limited`, `company`, `co.`, `inc.`, `ltd.`, `corp.`
      - Strip punctuation (`.,;:'"-`)
      - Collapse internal whitespace
- [ ] A group may contain PSRs from **exactly one** partition
- [ ] In-partition similarity is no longer fuzzy-gated (post-normalisation, exact equality
      is required) — `cp_threshold` is renamed to `bank_counterparty_min_similarity` and
      applies only between the bank debtor and the partition key
- [ ] "Trailing single-character difference" rule: if two normalised keys differ only in
      the last 1–2 characters AND those chars are a single letter or digit, they are
      considered **different partitions** (e.g. "batch customer a" vs "batch customer b" →
      different)
- [ ] `abc-recon` regression:
      - GRP-A group = `{9007, 9008, 9009}` matched to NTRY-USD-007
      - GRP-B group = `{9017, 9018}` matched to NTRY-USD-016
      - No mixed group ever forms

---

## Implementation Sketch

1. Add `normalise_counterparty(name: str) -> str` helper at top of `reconciliation.py`
   (near `similarity()`). Single function, ~10 lines. Document the normalisation rules in
   a one-line comment above the helper.
2. Add `trailing_single_char_diff(a: str, b: str) -> bool` helper that returns True when
   two strings differ only in their final 1–2 characters and the differing chars are
   alphanumeric.
3. In `find_one_to_many_groups()`, replace the current `candidates = [...]` block with:
   - Group residual PSRs by `normalise_counterparty(p.counterparty)`
   - For each `camt`, find the partition whose key is closest to
     `normalise_counterparty(camt.counterparty)` using exact-match first, then high-bar
     similarity (≥ `bank_counterparty_min_similarity`, default 0.95)
   - Reject the partition if `trailing_single_char_diff(...)` is True
   - Subset-sum runs only inside that single partition
4. Update pattern config defaults:
   - `P6.counterparty_threshold` → deprecate, keep accepted but log a warning
   - `P6.bank_counterparty_min_similarity` → new, default `0.95`

---

## Test Plan

- New unit tests in `tests/test_p6_partitioning.py`:
  - `test_normalise_strips_legal_suffixes`: "Acme LLC" and "acme" produce same key
  - `test_normalise_preserves_distinct_names`: "Acme" and "Acme Holdings" produce different keys
  - `test_trailing_char_diff_separates_sibling_entities`: "Batch Customer A" and "Batch Customer B" → different partitions
  - `test_p6_never_mixes_partitions`: fixture with two customers whose names differ by trailing letter, PSRs that could mathematically combine to match a bank amount → engine produces 0 groups, never a mixed one
- Extend `test_p6_one_to_many.py` `abc-recon` regression to assert the two distinct groups
- Run full suite, expect green

---

## Risks

- Aggressive suffix-stripping could over-merge: "Acme Corp" and "Acme Corp Holdings"
  normalise to "acme" vs "acme holdings" — these stay distinct, so we're fine.
- Real-world counterparty data may contain encoding artefacts (smart quotes, non-ASCII
  spaces). Document the limitation and add to backlog if it surfaces.

---

## Open Questions

1. Should branch/account suffixes ("Customer Foo - Branch 01" vs "Branch 02") be treated
   as different counterparties? **Recommended default: yes — different** (different ledger
   accounts in practice). Confirm with user before committing.
2. Configurable stripping list — keep in `Settings` (Python dataclass) or push into the
   `pattern_registry` rules JSON for runtime tunability? **Recommended: pattern_registry**
   so analysts can adjust without redeploy.

---

## Out of Scope

- Bank-side batch marker hints → TASK-36
- P4 fuzzy gate tightening (which would benefit from the same normalisation) → TASK-37
  (will reuse the helpers from this task)
