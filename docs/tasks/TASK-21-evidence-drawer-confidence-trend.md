# TASK-21 · Evidence Drawer — Stage 4b: Confidence Trend Indicator

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-14 (drawer clarity baseline — confidence must be correctly labelled before adding a trend)  
**Blocks:** —  
**Can run in parallel with:** TASK-15, TASK-16, TASK-17, TASK-19, TASK-20, TASK-22  
**Effort:** ~2 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 4, item 12

---

## Background

A single confidence score (e.g. 72%) is hard to contextualise. Is 72% good or bad for this rule type? Showing where this item sits relative to the batch average — and flagging outliers — lets users immediately identify which cases need extra scrutiny and which are routine.

No new API endpoints are needed: the batch confidence values are already present in the `results` list loaded by `ResultsWorkbench`.

---

## Acceptance Criteria

- [ ] The evidence drawer shows a small contextual line beneath the confidence figure:
  - Example: `"Batch average: 81% — this item is below average"`
  - Example: `"Batch average: 81% — this item is above average"`
  - Outlier threshold: ±20 percentage points from the batch mean → show an amber warning: `"Low outlier — significantly below batch average"`
- [ ] Batch average is computed from the current loaded `results.items` (not a new API call)
- [ ] The batch average calculation excludes items with `match_confidence = null` or `0`
- [ ] The trend line is visually subtle — small text, muted colour — it must not compete with the main confidence figure
- [ ] If fewer than 3 items have a confidence score (insufficient for a meaningful average), the trend line is hidden

---

## Implementation Notes

### Compute batch average in `ResultsWorkbench`

Pass `allItems` (the full current page) into `EvidenceDrawer` alongside the selected `item`:

```jsx
const batchAvg = useMemo(() => {
  const vals = results.items
    .map(r => r.match_confidence)
    .filter(v => v != null && v > 0);
  if (vals.length < 3) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}, [results.items]);
```

### Render in `EvidenceDrawer`

```jsx
{batchAvg != null && item.match_confidence != null && (
  <p className={`confidence-trend ${
    item.match_confidence < batchAvg - 20 ? 'outlier' : ''
  }`}>
    Batch average: {batchAvg.toFixed(0)}% —{' '}
    {item.match_confidence < batchAvg - 20
      ? '⚠ Low outlier — significantly below batch average'
      : item.match_confidence < batchAvg
        ? 'this item is below average'
        : 'this item is above average'}
  </p>
)}
```

### CSS (`App.css`)

```css
.confidence-trend       { font-size: 0.8rem; color: #6b7280; margin-top: 2px; }
.confidence-trend.outlier { color: #b45309; font-weight: 500; }
```
