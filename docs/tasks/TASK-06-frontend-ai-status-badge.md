# TASK-06 · Frontend — Show AI_SUGGESTED status badge in ResultTable

**Type:** Frontend  
**Branch:** `feature/residual-match-ai`  
**Depends on:** TASK-03 (endpoint must exist so AI cases appear in the DB)  
**Blocks:** TASK-07  
**Can run in parallel with:** TASK-05  
**Effort:** ~2 hours

---

## Background

Once AI triage runs (TASK-03, TASK-05), `recon_cases` will contain rows with two new `reconciliation_status` values:
- `"AI-Assisted Suggested Match"` — high-confidence embedding match (Tier 2b clear)
- `"AI - Analyst Adjudication Required"` — maybe-zone, possibly updated by Tier 2c LLM

These need a distinct visual treatment in the `ResultTable` component so analysts can immediately spot AI-generated suggestions vs deterministic results. The plan specifies **purple** colour and an **AI** icon/label.

---

## Acceptance Criteria

- [ ] `"AI-Assisted Suggested Match"` status renders with a purple badge
- [ ] `"AI - Analyst Adjudication Required"` status renders with a lighter purple / outline badge
- [ ] Both badges include a short `AI` prefix label (e.g. `AI · Suggested Match`)
- [ ] Badge colours do not conflict with existing status colours (green, amber, blue, red, grey, orange)
- [ ] Existing status badges are unchanged

---

## Implementation

### Step 1 — Locate status badge logic in `App.jsx`

Search for where `reconciliation_status` is rendered as a coloured badge. It will be inside the `ResultTable` component — look for a function or mapping like `statusBadge`, `statusClass`, or a conditional className string.

### Step 2 — Add the two new statuses to the badge map

The current badge map likely looks something like:
```jsx
const STATUS_COLOURS = {
  'Matched & Settled (Auto-Close)':        'badge-green',
  'Post to Short or Over Ledger':          'badge-amber',
  'Suggested Match – Analyst Review':      'badge-blue',
  'Exception – Amount Variance Review':    'badge-red',
  'Uncleared / In-Transit Payment':        'badge-grey',
  'Bank-only Item - Investigation':        'badge-orange',
};
```

Add:
```jsx
  'AI-Assisted Suggested Match':           'badge-purple',
  'AI - Analyst Adjudication Required':    'badge-purple-light',
```

### Step 3 — Add CSS for the new badge colours in `App.css`

Find the existing badge colour definitions and add:
```css
.badge-purple       { background: #7c3aed; color: #fff; }
.badge-purple-light { background: #ede9fe; color: #5b21b6; border: 1px solid #c4b5fd; }
```

### Step 4 — Add short display label for AI statuses (optional but recommended)

If the status string is displayed as-is in the badge, consider a display label map to keep badges compact:
```jsx
const STATUS_LABELS = {
  'AI-Assisted Suggested Match':        'AI · Suggested',
  'AI - Analyst Adjudication Required': 'AI · Review',
  // ... existing labels unchanged
};
```

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/App.jsx` | Add two new entries to status badge colour map; optionally add display label map |
| `frontend/src/App.css` | Add `.badge-purple` and `.badge-purple-light` CSS rules |

---

## Notes

- Purple is chosen because it is not used by any existing status and has strong visual connotation of "AI-generated" in modern UI conventions
- If the codebase uses inline styles instead of CSS classes for badges, apply the same colour values inline
- The `"AI · Review"` short label avoids the full status string overflowing in narrow table columns
