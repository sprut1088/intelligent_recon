# TASK-11 · Results Workbench — AI-Reviewed Row Indicators

**Type:** Frontend  
**Branch:** `fix/ui-result-workbench`  
**Depends on:** —  
**Blocks:** —  
**Can run in parallel with:** TASK-08, TASK-09, TASK-10, TASK-12, TASK-13  
**Effort:** ~1 hour

---

## Background

After AI triage runs, some cases that previously had status `"Uncleared / In-Transit Payment"`
may have been evaluated by the LLM and rejected (`TIER2C_NO_MATCH`). These cases are visually
indistinguishable from regular P5 exceptions that were never triaged. An analyst has no way to
know the AI already reviewed them without opening each case.

Similarly, there is no visual indicator on any row to signal it passed through the AI pipeline
at all — even for `AI-Assisted Suggested Match` rows, the status badge is the only signal and
it gets lost in a long table.

---

## Observations covered

| # | Description |
|---|---|
| 8 | `TIER2C_NO_MATCH` rows look identical to plain P5 exceptions in the table |
| 9 | No "AI reviewed" row-level indicator for cases that went through triage |

---

## Acceptance Criteria

- [ ] Any case with `rule_applied` starting with `TIER2C` or `TIER2B` shows a small **AI** pill/badge on the row (in addition to the status tag)
- [ ] `TIER2C_NO_MATCH` rows show the AI pill with a distinct muted/strikethrough style to indicate "AI reviewed — no match"
- [ ] `AI-Assisted Suggested Match` rows show the AI pill in the accent/purple colour
- [ ] The pill is compact and does not break row layout — position it inside the Case cell below the case ID, or in a dedicated narrow column
- [ ] Tooltip on the AI pill shows the rule applied (e.g. `TIER2C_LLM`, `TIER2B_EMBEDDING`)

---

## Implementation Notes

### AI pill helper
```jsx
function AiPill({ rule }) {
  if (!rule) return null;
  const isNoMatch = rule === 'TIER2C_NO_MATCH';
  const isAi = rule.startsWith('TIER2') || rule.startsWith('TIER2B');
  if (!isAi) return null;
  return (
    <span
      className={`ai-pill ${isNoMatch ? 'muted' : 'accent'}`}
      title={rule}
    >
      AI
    </span>
  );
}
```

Place inside the Case cell:
```jsx
<td>
  <strong>{r.result_id}</strong>
  <AiPill rule={r.rule_applied} />
  <br/>
  <span className="muted">{r.psr_id || '-'} / {r.camt_id || '-'}</span>
</td>
```

### CSS additions (`App.css` or `styles.css`)
```css
.ai-pill { font-size: 0.65rem; font-weight: 700; padding: 1px 5px; border-radius: 3px; margin-left: 4px; vertical-align: middle; }
.ai-pill.accent { background: var(--ai-accent, #7c3aed); color: #fff; }
.ai-pill.muted  { background: var(--border); color: var(--text-muted); text-decoration: line-through; }
```

---

## Files to change

- `frontend/src/App.jsx` — `ResultTable`, new `AiPill` component
- `frontend/src/App.css` or `frontend/src/styles.css` — pill styles
