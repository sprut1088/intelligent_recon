# TASK-14 · Evidence Drawer — Stage 1: Trust & Clarity Fixes

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** —  
**Blocks:** TASK-16, TASK-17, TASK-18, TASK-21  
**Can run in parallel with:** TASK-15  
**Effort:** ~2–3 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 1

---

## Background

Six low-effort, no-backend-dependency clarity issues in the evidence drawer that erode user trust before they even read the AI decision. These must be fixed first — subsequent stages build on a drawer the user already understands.

All changes are confined to the `EvidenceDrawer` component and its supporting CSS in `App.jsx` / `App.css`.

---

## Acceptance Criteria

- [ ] **#1 — Badge rename**: `"Check"` badges replaced with semantic state labels:
  - `passed: true` → green `"Pass"` badge
  - `passed: false` → red `"Fail"` badge
  - Score < 50 (low confidence component) → amber `"Low"` badge
- [ ] **#2 — Confidence contradiction resolved**: The narrative sentence no longer reads `"Confidence 0%"` when factor rows show non-zero weights. Either:
  - Display `engine_confidence` (the actual LLM/embedding confidence) in the narrative, **or**
  - Remove the confidence figure from the narrative and rely solely on the labelled progress bar
- [ ] **#3 — Progress bar labelled**: The horizontal bar is labelled `"Overall match confidence"` (or hidden if it duplicates the narrative figure)
- [ ] **#4 — Raw codes replaced with plain language**: Internal codes shown to users are replaced; the raw code appears in muted/secondary style for power users:
  - `TIER2C_NO_MATCH` → `"AI reviewed — no match found"` *(code muted below)*
  - `TIER2C_LLM` → `"AI reviewed — match suggested"` *(code muted below)*
  - `TIER2B_CLEAR` → `"Embedding match — high confidence"` *(code muted below)*
  - `TIER2B_MAYBE` / `AI_MAYBE_ZONE` → `"Embedding match — needs review"` *(code muted below)*
  - `P1_EXACT` / `P2_FUZZY` etc. → `"Deterministic rule match"` *(code muted below)*
  - Any unmapped code → fall back to displaying the code as-is (no crash)
- [ ] **#5 — Variance dash fixed**: When `variance` is `null`, `undefined`, or `—`, the Variance field in the drawer either:
  - Is hidden entirely, **or**
  - Displays `"N/A — no bank amount to compare"`
- [ ] **#6 — Repeated text eliminated**: The same sentence must not appear more than once across the three zones: header description, "Why this decision?" block, Suggested Actions. Each zone must contribute distinct information.

---

## Implementation Notes

### Badge component

Replace the existing badge/chip rendering for factor rows. The `passed` boolean comes from `feature_snapshot_json → score_breakdown → components[*].passed`. Add a `weight` field read to detect low-confidence threshold.

```jsx
function FactorBadge({ passed, weight }) {
  if (!passed) return <span className="badge fail">Fail</span>;
  if (weight < 50) return <span className="badge low">Low</span>;
  return <span className="badge pass">Pass</span>;
}
```

### Plain-language code map

Add a module-level constant in `App.jsx`:

```js
const RULE_LABELS = {
  TIER2C_NO_MATCH:  'AI reviewed — no match found',
  TIER2C_LLM:       'AI reviewed — match suggested',
  TIER2B_CLEAR:     'Embedding match — high confidence',
  TIER2B_MAYBE:     'Embedding match — needs review',
  AI_MAYBE_ZONE:    'Embedding match — needs review',
  P1_EXACT:         'Deterministic rule match',
  P2_FUZZY:         'Deterministic rule match',
  P3_PARTIAL:       'Deterministic rule match',
  P4_RAPIDFUZZ:     'Deterministic rule match',
};
const ruleLabel = (code) => RULE_LABELS[code] ?? code;
```

Render as:
```jsx
<span>{ruleLabel(rule_applied)}</span>
<span className="text-muted small">{rule_applied}</span>
```

### CSS additions (`App.css`)

```css
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600; }
.badge.pass  { background: #d1fae5; color: #065f46; }
.badge.fail  { background: #fee2e2; color: #991b1b; }
.badge.low   { background: #fef3c7; color: #92400e; }
.text-muted  { color: #9ca3af; }
.small       { font-size: 0.75rem; }
```
