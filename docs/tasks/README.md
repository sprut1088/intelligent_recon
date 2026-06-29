# Task Index

Reference: [docs/AI_TRIAGE_PLAN.md](../AI_TRIAGE_PLAN.md)  
Reference: [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md)

---

## Dependency Map — AI Triage branch (`feature/residual-match-ai`)

```
TASK-01  rapidfuzz P4 upgrade
    │
    └──► TASK-02  ai_triage.py (Tier 2b: pre-filter + embeddings)
              │
              └──► TASK-03  POST /api/reconcile/ai-triage endpoint
                        │
                        ├──► TASK-04  Tier 2c LLM adjudication (extend TASK-02 + TASK-03)
                        │
                        ├──► TASK-05  Frontend: API client + "Run AI triage" button ──┐
                        │                                                              │
                        └──► TASK-06  Frontend: AI status badge in ResultTable ────────┤
                                                                                       │
                                                                            TASK-07  Resolve modal AI pre-fill
```

## Dependency Map — Results Workbench UI (`fix/ui-result-workbench`)

```
TASK-08  Search UX & status filter
TASK-09  Pagination & record count
    │
    └──► TASK-13  Summary bar (uses pagination state)

TASK-10  Column sorting & variance colour fix
TASK-11  AI-reviewed row indicators
TASK-12  Evidence drawer improvements
```

TASK-08, TASK-09, TASK-10, TASK-11, TASK-12 are all independent and can run in parallel.
TASK-13 depends on TASK-09 for pagination state.

---

## Task Summary — AI Triage (`feature/residual-match-ai`)

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-01](TASK-01-rapidfuzz-p4-upgrade.md) | Upgrade P4 fuzzy matching to rapidfuzz | Backend | — | ✅ Complete |
| [TASK-02](TASK-02-ai-triage-tier2b-embeddings.md) | Create `ai_triage.py` — Tier 2b embeddings | Backend | TASK-01 | ✅ Complete |
| [TASK-03](TASK-03-ai-triage-endpoint.md) | Add `POST /api/reconcile/ai-triage` endpoint | Backend | TASK-02 | ✅ Complete |
| [TASK-04](TASK-04-ai-triage-tier2c-llm.md) | Tier 2c LLM adjudication | Backend | TASK-02, TASK-03 | ✅ Complete |
| [TASK-05](TASK-05-frontend-ai-triage-button.md) | Frontend: API client + Run AI triage button | Frontend | TASK-03 | ✅ Complete |
| [TASK-06](TASK-06-frontend-ai-status-badge.md) | Frontend: AI status badge in ResultTable | Frontend | TASK-03 | ✅ Complete |
| [TASK-07](TASK-07-frontend-resolve-modal-ai-prefill.md) | Frontend: pre-fill Resolve modal from AI suggestion | Frontend | TASK-05, TASK-06 | ✅ Complete |

## Task Summary — Results Workbench UI (`fix/ui-result-workbench`)

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-08](TASK-08-rw-search-and-filter.md) | Search UX & status filter dropdown | Frontend | — | ✅ Complete |
| [TASK-09](TASK-09-rw-pagination-and-count.md) | Pagination & record count | Frontend | — | ✅ Complete |
| [TASK-10](TASK-10-rw-sorting-and-variance-colour.md) | Column sorting & variance colour fix | Frontend | — | ✅ Complete |
| [TASK-11](TASK-11-rw-ai-reviewed-row-indicators.md) | AI-reviewed row indicators | Frontend | — | ✅ Complete |
| [TASK-12](TASK-12-rw-evidence-drawer-improvements.md) | Evidence drawer improvements | Frontend | — | ✅ Complete |
| [TASK-13](TASK-13-rw-summary-bar.md) | Toolbar summary bar | Frontend | TASK-09 | ✅ Complete |

---

## Dependency Map — Evidence Drawer UX (`feat/evidence-drawer-ux`)

```
TASK-14  Stage 1: clarity fixes (badges, confidence, codes, variance, repeated text)
    │
    ├──► TASK-17  Action-oriented suggested actions  ──────────────────────────────┐
    │                                                                               │
    └──► TASK-21  Confidence trend (independent once drawer is clean)              │
                                                                                   ▼
TASK-15  Backend: surface raw PSR/CAMT fields ──► TASK-16  Field diff ──► TASK-18  Split CTA
                                                       │                       │
                                                  TASK-22  Source links   TASK-19  Override reason capture
                                                                               │
                                                                    ┌──────────┴──────────┐
                                                                    │                      │
                                                               TASK-20  Similar cases  TASK-23  Filter nav
                                                                                           │
                                                                                       TASK-24  Keyboard shortcuts

TASK-19 + TASK-23 ──► TASK-25  Bulk resolution
```

## Task Summary — Evidence Drawer UX (`feat/evidence-drawer-ux`)

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-14](TASK-14-evidence-drawer-stage1-clarity.md) | Stage 1: trust & clarity fixes | Frontend | — | ✅ Complete |
| [TASK-15](TASK-15-backend-surface-raw-fields.md) | Backend: surface raw PSR/CAMT fields | Backend | — | ✅ Complete |
| [TASK-16](TASK-16-evidence-drawer-field-diff.md) | Side-by-side field diff | Frontend | TASK-14, TASK-15 | ✅ Complete |
| [TASK-17](TASK-17-evidence-drawer-action-labels.md) | Action-oriented suggested actions | Frontend | TASK-14 | ✅ Complete |
| [TASK-18](TASK-18-evidence-drawer-split-cta.md) | Split resolve CTA | Frontend | TASK-16, TASK-17 | ✅ Complete |
| [TASK-19](TASK-19-override-reason-capture.md) | Override reason capture | Full-stack | TASK-18 | ✅ Complete |
| [TASK-20](TASK-20-evidence-drawer-similar-cases.md) | Similar resolved cases panel | Full-stack | TASK-19 | ✅ Complete |
| [TASK-21](TASK-21-evidence-drawer-confidence-trend.md) | Confidence trend indicator | Frontend | TASK-14 | ✅ Complete |
| [TASK-22](TASK-22-evidence-drawer-source-links.md) | Direct links to source records | Frontend | TASK-15 | ✅ Complete |
| [TASK-23](TASK-23-evidence-drawer-filter-navigation.md) | Filterable drawer navigation | Frontend | TASK-14–19 | ✅ Complete |
| [TASK-24](TASK-24-evidence-drawer-keyboard-shortcuts.md) | Keyboard shortcuts | Frontend | TASK-23 | ✅ Complete |
| [TASK-25](TASK-25-bulk-resolution.md) | Bulk resolution | Full-stack | TASK-19, TASK-23 | � Deferred — await per-item flow validation + auth/RBAC decision |

---
## Dependency Map — P6 One-to-Many Execution (`feat/one-2-many`)

```
TASK-26  DB schema + ReconCase dataclass (group_id, group_role) + P6 seed update
    │
    └──► TASK-27  find_one_to_many_groups() core algorithm
              │
              └──► TASK-28  Wire P6 into reconcile_transactions() cascade
                        │
                        ├──► TASK-29  Group-aware resolve endpoint (member → anchor routing)
                        │
                        ├──► TASK-31  Frontend: group badge + EvidenceDrawer sibling panel
                        │             (depends on TASK-28 + TASK-29)
                        │
                        └──► TASK-32  Tests: P6 fixtures + 6 test scenarios
                                      (depends on TASK-28 + TASK-29)

TASK-30  P10 honesty fix (rename candidate label + log line)
         ← independent of TASK-26–29, can run in parallel
```

## Task Summary — P6 One-to-Many Execution (`feat/one-2-many`)

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-26](TASK-26-p6-schema-and-dataclass.md) | DB schema + `ReconCase` dataclass + P6 seed | Backend | — | ✅ Complete |
| [TASK-27](TASK-27-p6-core-algorithm.md) | `find_one_to_many_groups()` core algorithm | Backend | TASK-26 | ✅ Complete |
| [TASK-28](TASK-28-p6-wire-into-cascade.md) | Wire P6 into `reconcile_transactions()` cascade | Backend | TASK-27 | ✅ Complete |
| [TASK-29](TASK-29-p6-group-aware-resolve.md) | Group-aware resolve endpoint | Backend | TASK-28 | ✅ Complete |
| [TASK-30](TASK-30-p10-honesty-fix.md) | P10 honesty fix (rename + log line) | Backend | — | ✅ Complete |
| [TASK-31](TASK-31-p6-frontend-group-ui.md) | Frontend: group badge + EvidenceDrawer sibling panel | Frontend | TASK-28, TASK-29 | ✅ Complete |
| [TASK-32](TASK-32-p6-tests.md) | Tests: P6 fixtures and 6 test scenarios | Backend | TASK-28, TASK-29 | ✅ Complete |

### Recommended pickup order

#### Solo developer
```
TASK-30 (quick independent fix, any time)
TASK-26 → TASK-27 → TASK-28 → TASK-29 → TASK-31 + TASK-32 (parallel)
```

#### Two developers
```
Dev A: TASK-26 → TASK-27 → TASK-28 → TASK-29 → TASK-32
Dev B: TASK-30 (immediate) → wait for TASK-28+29 → TASK-31
```

---
## Task Summary — Results Workbench Export (`feat/rw-export`)

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-33](TASK-33-results-workbench-export.md) | Download reconciliation report from Results Workbench | Full-stack | — | ✅ Complete |

---

## Dependency Map — Reconciliation Engine Correctness (`feat/recon-correctness` + `feat/p10-split-settlement`)

Source: `abc-recon-20260629` regression analysis — three real defects + one known gap.

```
TASK-34  Cascade re-order: P4 runs AFTER P6 (unblocks downstream fixes)
    │
    ├──► TASK-35  P6 strict counterparty partitioning (normalisation + trailing-char rule)
    │       │
    │       └──► TASK-36  P6 bank-side batch marker seeding (reuses TASK-35 helpers)
    │
    └──► TASK-37  Tighten P4 fuzzy gate (corroboration required, threshold raised,
                  reuses TASK-35 helpers)

TASK-38  P10 split settlement (1 PSR → N CAMT) — new branch `feat/p10-split-settlement`
         depends on TASK-34 landing first
```

**Defect coverage map:**

| Defect (from abc-recon analysis) | Fixed by |
|---|---|
| 1. P4 cannibalised P6 batch member (TX-9009 → wrong CAMT) | TASK-34 (primary), TASK-37 (belt-and-braces) |
| 2. P6 mixed two customers into one group | TASK-35 (primary), TASK-36 (reinforcement) |
| 3. Variance band misclassification (TX-9015) | _Configuration only — no task, owner adjusts thresholds_ |
| 4. Split settlement unsupported (TX-9010) | TASK-38 |

## Task Summary — Reconciliation Engine Correctness

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-34](TASK-34-cascade-reorder-p6-before-p4.md) | Cascade re-order: P6 before P4 | Backend | — | ✅ Complete |
| [TASK-35](TASK-35-p6-strict-counterparty-partitioning.md) | P6 strict counterparty partitioning | Backend | TASK-34 | 🔲 Not started |
| [TASK-36](TASK-36-p6-bank-batch-marker-seeding.md) | P6 bank-side batch marker seeding | Backend | TASK-35 | 🔲 Not started |
| [TASK-37](TASK-37-tighten-p4-fuzzy-gate.md) | Tighten P4 fuzzy gate (corroboration required) | Backend | TASK-34, TASK-35 | 🔲 Not started |
| [TASK-38](TASK-38-p10-split-settlement.md) | P10 split settlement (1 PSR → N CAMT) | Backend | TASK-34 | 🔲 Not started |

### Suggested merge order

```
TASK-34 → TASK-37 → TASK-35 → TASK-36   (all on feat/recon-correctness)
TASK-38                                  (separate branch feat/p10-split-settlement)
```

Rationale:
- TASK-34 is small but unlocks the rest — land it first.
- TASK-37 stops P4 from producing overconfident false-positives immediately after.
- TASK-35 + TASK-36 then make P6 deterministically correct on multi-customer batches.
- TASK-38 is largest and structurally independent — separate branch keeps PR review tractable.

### Definition of Done — Recon-correctness branch

- [ ] TASK-34, TASK-35, TASK-36, TASK-37 all complete and verified
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions
- [ ] **abc-recon regression** (new fixture `backend/sample_data/regression_abc/`) runs end-to-end and matches expected output: GRP-A `{9007,9008,9009}` and GRP-B `{9017,9018}` form correctly; CASE-000006 (mis-routed 9009) does not appear; no mixed-customer groups exist
- [ ] No P4 case has `match_confidence > 89`
- [ ] No P4 case is emitted without a corroborating signal
- [ ] Branch merged to `feature/development` via PR with reviewer approval

### Definition of Done — P10 split-settlement branch

- [ ] TASK-38 complete and verified
- [ ] abc-recon regression: TX-9010 forms a `1_TO_N` group with NTRY-USD-008 + NTRY-USD-009 at confidence 92
- [ ] CASE-000018, CASE-000020, CASE-000021 disappear from output (replaced by the group)
- [ ] Frontend EvidenceDrawer sibling panel renders the split group without code changes
- [ ] Branch merged to `feature/development` via PR with reviewer approval

---
### Definition of Done — P6 branch

- [ ] All 7 tasks completed and individually verified
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions
- [ ] Load `psr_test_50.txt` + `camt_test_50.xml`, run reconcile — P6 cases appear when
      sample data contains batchable transactions
- [ ] P6 anchor rows have `group_role = "ANCHOR"`, `internal_amount = group sum`,
      `match_type = "N_TO_1"`
- [ ] P6 member rows have `group_role = "MEMBER"`, `bank_amount = null`, `variance = null`
- [ ] Resolving a member case_id → all siblings cleared, one resolution row written
- [ ] `learning_eligible = 0` on all P6-originated resolutions
- [ ] Frontend shows N→1 badge on P6 rows; EvidenceDrawer shows sibling panel
- [ ] Branch merged to `feature/development` via PR with reviewer approval

---
## Recommended Pickup Order

### Solo developer — AI Triage
```
TASK-01 → TASK-02 → TASK-03 → TASK-05 → TASK-06 → TASK-07 → TASK-04
```

### Solo developer — Results Workbench UI
```
TASK-08 + TASK-10 + TASK-11  (parallel, independent)
TASK-09 → TASK-13
TASK-12  (independent, slightly larger)
```

### Two developers — Results Workbench UI
```
Dev A: TASK-08, TASK-09, TASK-13
Dev B: TASK-10, TASK-11, TASK-12
```

### Solo developer — Evidence Drawer UX
```
Stage 1+2 (foundation):  TASK-14 + TASK-15 (parallel) → TASK-16 + TASK-17 (parallel) → TASK-18 → TASK-19
Stage 3 (context):       TASK-20 + TASK-21 + TASK-22 (all parallel, after their deps)
Stage 4 (efficiency):    TASK-23 → TASK-24
Stage 5 (scale):         TASK-25 (only after TASK-19 + TASK-23)
```

### Two developers — Evidence Drawer UX
```
Dev A: TASK-14 → TASK-17 → TASK-18 → TASK-19 → TASK-23 → TASK-25
Dev B: TASK-15 → TASK-16 → TASK-22 (then TASK-20, TASK-21, TASK-24 in parallel)
```

---

## Recommended Pickup Order

### Solo developer
```
TASK-01 → TASK-02 → TASK-03 → TASK-05 → TASK-06 → TASK-07 → TASK-04
```
Do TASK-04 (LLM) last — it requires an API key and external dependency. Everything else works without it.

### Two developers
```
Dev A: TASK-01 → TASK-02 → TASK-03 → TASK-04
Dev B:                      TASK-05 + TASK-06 (parallel, once TASK-03 is merged) → TASK-07
```

---

## Definition of Done (for the full branch)

- [ ] All 7 tasks completed and individually verified
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions
- [ ] Load `psr_test_50.txt` + `camt_test_50.xml`, run deterministic reconcile, then click "Run AI triage" — see AI-suggested cases appear with purple badge
- [ ] Open an AI-suggested case → Resolve modal shows "AI pre-filled" label with pre-populated reason and comment
- [ ] Confirm a case → it moves to `"Resolved Manually"` and learning signal is captured
- [ ] Branch merged to `feature/development` via PR with reviewer approval

---

## Out of Scope for this Branch

All Future State items from `AI_TRIAGE_PLAN.md` (FS-1 through FS-6) are explicitly excluded:
- FS-1: Counterparty outreach email drafting
- FS-2: Batch root cause summaries
- FS-3: Entity resolution graph
- FS-4: Generative audit explainability
- FS-5: AI suggestion persistence (production durability)
- FS-6: AI-assisted rule drafting
