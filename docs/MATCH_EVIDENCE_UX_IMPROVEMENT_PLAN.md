# Match Evidence Drawer — UX Improvement Plan

**Date:** 2026-06-15  
**Scope:** Evidence drawer / triage panel shown when reviewing reconciliation exceptions  
**Status:** Planning

---

## Context

The Match Evidence drawer is the primary interface through which business users review AI triage decisions and resolve reconciliation exceptions. As the most interaction-heavy surface in the application, its quality directly affects user trust in the AI, resolution accuracy, and learning signal quality.

This document captures the identified problems, proposed improvements, and a prioritised staging plan.

---

## Identified Problems

### Clarity & Information Architecture

- **Confidence contradiction** — "Confidence 0%" appears in the narrative while factor rows show 60% and 40%. It is unclear whether those percentages are factor *weights* (contribution to the decision) or factor *scores* (how well each factor performed). Users lose trust when numbers contradict.
- **Repeated text** — The same sentence ("The CAMT entry does not match the counterparty name of the PSR payment record") appears three times: in the header description, in the "Why this decision?" block, and in Suggested Actions. This makes the panel feel padded rather than informative.
- **Raw technical codes exposed** — `TIER2C_NO_MATCH`, `AI_MAYBE_ZONE` are internal system identifiers meaningless to business users. They need plain-language equivalents; codes should be secondary/muted for power users only.
- **Unlabelled progress bar** — A bar appears between the narrative and factor rows with no label. Its meaning (overall confidence? match score?) is ambiguous.
- **Variance dash** — Showing `—` for variance provides no information. Either hide it when not applicable or replace with "N/A — no amount to compare".

### Evidence Quality

- **No actual data shown** — The user is told a conclusion (names don't match) but never shown the CAMT value alongside the PSR value. There is no "show your work" moment. Users must blindly trust the AI decision.

### Resolution Flow

- **"Check" badge is ambiguous** — Orange badges labelled "Check" carry no clear semantic meaning. Do they mean the factor passed? Failed? Needs review?
- **Suggested Actions are passive** — `NO_MATCH` is a status label, not an action. Users need action-oriented language: "Mark as No Match", "Escalate for Review", "Override: Accept as Match".
- **Single CTA conflates two operations** — "Resolve and capture learning" does two distinct things in one click. Users who want to override (disagreeing with the AI) generate the same learning signal as users who agree. This corrupts the training feedback loop.

### Navigation & Workflow

- **Linear navigation with no escape hatch** — "1/16 Prev/Next" forces sequential review with no way to filter by confidence, status, or rule. Users handling large batches cannot prioritise.
- **No keyboard shortcuts** — Power users triaging high volumes need keyboard-driven navigation.

---

## Proposed Improvements

### New Functionality

1. **Side-by-side field diff** — Two-column CAMT vs PSR comparison with mismatched fields highlighted. The foundational "show your work" feature.
2. **Override with reason capture** — When overriding the AI, prompt the user for a reason (dropdown: "Same entity, different name format", "Known alias", "Data entry error", etc.). Tags learning signal as agreement vs. override with context.
3. **Similar resolved cases** — "3 similar counterparty mismatches in this batch were resolved as No Match." Builds confidence in repetitive decisions.
4. **Bulk resolution** — Select multiple filtered items and apply the same resolution with a shared reason.
5. **Confidence trend indicator** — Show where this item sits relative to the batch average. Outliers with anomalously low confidence surface automatically.
6. **Direct links to source records** — Clickable invoice/counterparty IDs opening the raw CAMT or PSR entry.
7. **Keyboard shortcuts** — `←` / `→` navigate, `R` resolve, `S` skip, `O` override.
8. **Filterable navigation** — Replace Prev/Next with filter by status, confidence band, or rule applied.

---

## Staging Plan

Stages are ordered by dependency and impact. Each stage builds on the previous; skipping stages creates compounding UX debt.

---

### Stage 1 — Fix the Basics *(Trust & Clarity)*
> Low effort. No dependencies. Do first — a confused user won't trust the AI decisions that follow.

| # | Change |
|---|--------|
| 1 | Rename "Check" badges to semantic states: Pass / Fail / Low Confidence |
| 2 | Resolve confidence contradiction — reconcile "0%" narrative with factor percentages; clarify if percentages are weights or scores |
| 3 | Label the progress bar (e.g., "Overall match confidence") or remove it |
| 4 | Replace raw codes with plain language; show codes as secondary muted text |
| 5 | Fix Variance dash — hide when not applicable or show "N/A — no amount to compare" |
| 6 | Eliminate repeated text — header states the finding once; explanation section must add new information |

---

### Stage 2 — Show the Actual Data *(unlocks everything downstream)*
> The single highest-impact change. Without this, override and learning features have no foundation.

| # | Change |
|---|--------|
| 7 | **Side-by-side field diff** — two-column CAMT vs PSR with mismatched field highlighted |
| 8 | **Action-oriented Suggested Actions** — "Mark as No Match", "Escalate for Review", "Override: Accept as Match" — meaningful now that the user can see the data |

---

### Stage 3 — Smarter Resolution Flow
> Depends on Stage 2. Once the user can see evidence and has meaningful action choices, the resolution flow must match.

| # | Change |
|---|--------|
| 9 | **Split the CTA** — separate "Resolve" from "Capture learning"; distinguish agreement from override |
| 10 | **Override reason capture** — when user selects Override, prompt a reason dropdown; tag learning signal accordingly |

---

### Stage 4 — Build Confidence Through Context
> Depends on Stage 3. Resolved cases and learning data must exist before they can be surfaced.

| # | Change |
|---|--------|
| 11 | **Similar resolved cases** — show count and outcome of similar past decisions in the batch |
| 12 | **Confidence trend** — show this item's confidence relative to batch average; highlight outliers |
| 13 | **Direct links to source records** — clickable invoice/counterparty IDs (independent but most useful here) |

---

### Stage 5 — Navigation & Workflow Efficiency
> Only valuable once the per-item experience (Stages 1–4) is solid. Efficient navigation through a confusing panel just means mistakes happen faster.

| # | Change |
|---|--------|
| 14 | **Filterable navigation** — filter by status, confidence band, rule applied; replace Prev/Next-only flow |
| 15 | **Keyboard shortcuts** — `←`/`→` navigate, `R` resolve, `S` skip, `O` override |

---

### Stage 6 — Scale
> Depends on Stage 5 (filter navigation) and Stage 3 (reason capture) both being mature.

| # | Change |
|---|--------|
| 16 | **Bulk resolution** — select filtered items, apply resolution + shared reason; safe only after override reason capture and filter navigation are in place |

---

## Dependency Chain

```
Stage 1 (clarity)
  └── Stage 2 (field diff + action-oriented actions)
        └── Stage 3 (split CTA + override reasons)
              └── Stage 4 (similar cases + trends)

Stage 5 (navigation)
  └── Stage 6 (bulk resolution) ← also requires Stage 3
```

---

## Notes

- Stage 1 items can be shipped independently as a patch with no backend changes.
- Stage 2 item 7 (field diff) requires the backend to surface the raw CAMT and PSR field values alongside the triage result — verify this is available in the existing API response before starting frontend work.
- Stage 3 item 10 (override reason capture) has a model training implication — the learning endpoint must distinguish agreement signals from override signals.
- Stage 6 bulk resolution should not be built until the learning signal tagging (Stage 3) is solid, otherwise bulk actions will inject uncategorised noise into the model.
