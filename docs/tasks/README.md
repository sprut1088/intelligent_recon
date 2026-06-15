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
| [TASK-20](TASK-20-evidence-drawer-similar-cases.md) | Similar resolved cases panel | Full-stack | TASK-19 | 🔲 Not started |
| [TASK-21](TASK-21-evidence-drawer-confidence-trend.md) | Confidence trend indicator | Frontend | TASK-14 | 🔲 Not started |
| [TASK-22](TASK-22-evidence-drawer-source-links.md) | Direct links to source records | Frontend | TASK-15 | 🔲 Not started |
| [TASK-23](TASK-23-evidence-drawer-filter-navigation.md) | Filterable drawer navigation | Frontend | TASK-14…TASK-19 | 🔲 Not started |
| [TASK-24](TASK-24-evidence-drawer-keyboard-shortcuts.md) | Keyboard shortcuts | Frontend | TASK-23 | 🔲 Not started |
| [TASK-25](TASK-25-bulk-resolution.md) | Bulk resolution | Full-stack | TASK-19, TASK-23 | 🔲 Not started |

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
