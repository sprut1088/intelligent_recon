# Task Index — `feature/residual-match-ai`

Reference: [docs/AI_TRIAGE_PLAN.md](../AI_TRIAGE_PLAN.md)

---

## Dependency Map

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

**TASK-05 and TASK-06 can be worked in parallel** — they touch different parts of the frontend and have no dependency on each other.

---

## Task Summary

| Task | Title | Type | Depends on | Status |
|---|---|---|---|---|
| [TASK-01](TASK-01-rapidfuzz-p4-upgrade.md) | Upgrade P4 fuzzy matching to rapidfuzz | Backend | — | ✅ Complete |
| [TASK-02](TASK-02-ai-triage-tier2b-embeddings.md) | Create `ai_triage.py` — Tier 2b embeddings | Backend | TASK-01 | ✅ Complete |
| [TASK-03](TASK-03-ai-triage-endpoint.md) | Add `POST /api/reconcile/ai-triage` endpoint | Backend | TASK-02 | ✅ Complete |
| [TASK-04](TASK-04-ai-triage-tier2c-llm.md) | Tier 2c LLM adjudication | Backend | TASK-02, TASK-03 | 🔲 Not started |
| [TASK-05](TASK-05-frontend-ai-triage-button.md) | Frontend: API client + Run AI triage button | Frontend | TASK-03 | 🔲 Not started |
| [TASK-06](TASK-06-frontend-ai-status-badge.md) | Frontend: AI status badge in ResultTable | Frontend | TASK-03 | 🔲 Not started |
| [TASK-07](TASK-07-frontend-resolve-modal-ai-prefill.md) | Frontend: pre-fill Resolve modal from AI suggestion | Frontend | TASK-05, TASK-06 | 🔲 Not started |

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
