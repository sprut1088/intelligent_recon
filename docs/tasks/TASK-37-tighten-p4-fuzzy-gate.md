# TASK-37 · Tighten P4 fuzzy gate

**Type:** Backend
**Branch:** `feat/recon-correctness`
**Depends on:** TASK-34 (cascade order), TASK-35 (reuses normalisation helpers)
**Blocks:** None
**Effort:** ~3–4 hours

---

## Background

P4 (`P4_COUNTERPARTY_FUZZY`) currently matches a PSR to an unused CAMT entry when:
- `psr.amount == camt.amount` (exact)
- `similarity(psr.counterparty, camt.counterparty) >= 0.85`

With no other corroborating signal, this produces a "Suggested Match - Analyst Review"
at `int(score * 100)` confidence — which in practice can be 85–99% and looks
authoritative to an analyst clearing a queue.

In the `abc-recon` regression, P4 produced 3 suggestions:

| PSR | CAMT | sim | confidence | analyst expected |
|---|---|---|---|---|
| 9005 (Northwind Trading **Company**) | NTRY-005 (**Co.**) | 0.89 | 89 | 82 — correct |
| 9009 (Batch Customer **A**, GRP-A member) | NTRY-016 (Customer **B**) | 0.94 | 94 | **wrong match entirely** |
| 9014 (Green Valley **Supplies**) | NTRY-013 (**Supply**) | 0.91 | 91 | 65 — overconfident |

TASK-34 stops 9009 from being misrouted (P6 grabs it first). But P4 still:
1. Produces a 91% suggestion for "Supplies" vs "Supply" with no corroborating evidence
2. Has no defence against sibling-entity name patterns (Customer A vs B, Branch 01 vs 02)
3. Doesn't penalise abbreviation-only matches differently from genuine fuzziness

This task hardens P4 so the suggestions it produces are trustworthy.

---

## Acceptance Criteria

- [ ] P4 similarity floor raised from **0.85 → 0.92**
- [ ] P4 requires at least one **corroborating signal** to fire:
      - Shared PMT-REF substring (any non-trivial overlap, e.g. ≥5 chars), OR
      - Shared invoice substring (≥5 chars), OR
      - PSR `execution_date` within ±1 day of CAMT `value_date`/`booking_date` AND amount exact
- [ ] PSRs that pass the new corroboration gate emit P4 case at confidence
      `int(score * 100)` capped at **89** (so it never looks auto-closable)
- [ ] PSRs with high similarity but no corroboration emit **no P4 case** — they fall
      through to P5 (exception queue)
- [ ] P4 reuses `trailing_single_char_diff()` from TASK-35: if the diff is detected, P4
      does not fire regardless of similarity score
- [ ] P4 reuses `normalise_counterparty()` from TASK-35: matching is done on normalised
      keys, so "Northwind Trading Company" vs "Northwind Trading Co." continues to match
      (legal-suffix abbreviation is the **intended** case)
- [ ] `abc-recon` regression:
      - 9005 ↔ NTRY-005 still produces a P4 suggestion (normalised: both → "northwind trading")
      - 9014 ↔ NTRY-013 still produces a P4 suggestion (Supplies vs Supply — close, not trailing-char-diff)
      - 9009 ↔ NTRY-016 produces **no** P4 suggestion (caught by trailing-char-diff;
        belt-and-braces alongside TASK-34's cascade fix)

---

## Implementation Sketch

In `reconcile_transactions()` post-P6 P4 pass (created in TASK-34):

```python
# pseudocode
psr_key = normalise_counterparty(psr.counterparty)
cand_key = normalise_counterparty(cand.counterparty)
if trailing_single_char_diff(psr_key, cand_key):
    continue
score = similarity(psr_key, cand_key)
if score < 0.92:
    continue
corroborated = (
    shared_substring(psr.reference, cand.pmt_ref, min_len=5) or
    shared_substring(psr.invoice, cand.invoice, min_len=5) or
    date_within(psr.execution_date, cand.value_date or cand.booking_date, days=1)
)
if not corroborated:
    continue
conf = min(int(score * 100), 89)
# emit P4 case at conf
```

Helpers:
- `shared_substring(a, b, min_len)` — return True when both strings share a common
  substring of length ≥ `min_len`. Use Python's `difflib.SequenceMatcher.find_longest_match`.
- `date_within(d1, d2, days)` — reuse `safe_date_diff()` already in `reconciliation.py`.

Config (new pattern_registry keys for P4):
- `P4.similarity_floor` → default 0.92 (was 0.85)
- `P4.confidence_cap` → default 89
- `P4.corroboration_required` → default True
- `P4.shared_substring_min_len` → default 5
- `P4.date_window_days` → default 1

Backwards-compat: if `P4.threshold` is present (old key), treat it as `similarity_floor`
and log a deprecation notice once at startup.

---

## Test Plan

- New unit tests in `tests/test_p4_corroboration.py`:
  - `test_p4_requires_corroboration`: PSR+CAMT with similarity 0.95, exact amount, but
    no shared ref/invoice and date >1 day apart → no P4 case
  - `test_p4_fires_with_shared_pmt_ref`: same as above with shared PMT-REF substring → P4 fires
  - `test_p4_fires_with_date_corroboration`: shared date within ±1 day, exact amount → P4 fires
  - `test_p4_blocks_trailing_char_diff`: "Customer A" vs "Customer B" with shared invoice → no P4 case (trailing-char rule wins)
  - `test_p4_legal_suffix_normalises`: "Northwind Trading Company" vs "Northwind Trading Co." → matches at full score
  - `test_p4_confidence_capped_at_89`: similarity 0.99 with corroboration → confidence = 89
- Run full suite, audit for tests that asserted P4 confidence > 89 or fired without corroboration

---

## Risks

- The new gate is strictly tighter, so some true-positive P4 matches in existing test data
  will stop firing. Those PSRs will land in P5 exception queue instead — which is the
  intended outcome (better to ask the analyst than auto-suggest the wrong CAMT).
- The shared-substring check uses `difflib` which is O(n*m) — fine for typical PSR/CAMT
  string sizes (< 80 chars). If perf shows up as an issue, swap for rapidfuzz.

---

## Out of Scope

- Replacing the entire fuzzy library (rapidfuzz upgrade is already done in TASK-01)
- Machine-learned counterparty resolution (Tier 2c LLM territory)
