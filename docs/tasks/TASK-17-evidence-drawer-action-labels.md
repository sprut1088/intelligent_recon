# TASK-17 · Evidence Drawer — Stage 2b: Action-Oriented Suggested Actions

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-14 (drawer clarity baseline)  
**Blocks:** TASK-18  
**Can run in parallel with:** TASK-15, TASK-16  
**Effort:** ~1–2 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 2, item 8

---

## Background

Currently the "Suggested Actions" section in the drawer displays raw status codes like `NO_MATCH` or `CONFIRM_AI_MATCH`. These are system labels, not instructions. This task replaces them with action-oriented language so the user knows exactly what each button will do.

This is a purely cosmetic/labelling change — the underlying API calls and data model do not change.

---

## Acceptance Criteria

- [ ] `CONFIRM_AI_MATCH` suggestion renders as: **"Accept AI Match"** (primary button, green/blue)
- [ ] `ROUTE_TO_ANALYST` suggestion renders as: **"Escalate for Review"** (secondary button)
- [ ] `NO_MATCH` suggestion renders as: **"Mark as No Match"** (secondary/destructive button)
- [ ] Each button includes a one-line description underneath explaining the consequence:
  - Accept AI Match → *"Mark this PSR as matched to the suggested bank entry"*
  - Escalate for Review → *"Send to analyst queue for manual verification"*
  - Mark as No Match → *"Record this PSR as unmatched; no bank entry corresponds"*
- [ ] If `suggestions_json` is empty or null, the section is hidden (no empty box)
- [ ] Button click behaviour is unchanged from current implementation

---

## Implementation Notes

### Action map constant

Add to `App.jsx` near `RULE_LABELS`:

```js
const ACTION_CONFIG = {
  CONFIRM_AI_MATCH: {
    label: 'Accept AI Match',
    desc:  'Mark this PSR as matched to the suggested bank entry.',
    style: 'btn primary',
  },
  ROUTE_TO_ANALYST: {
    label: 'Escalate for Review',
    desc:  'Send to analyst queue for manual verification.',
    style: 'btn secondary',
  },
  NO_MATCH: {
    label: 'Mark as No Match',
    desc:  'Record this PSR as unmatched; no bank entry corresponds.',
    style: 'btn danger',
  },
};
const actionConfig = (code) => ACTION_CONFIG[code] ?? { label: code, desc: '', style: 'btn secondary' };
```

### Render in `EvidenceDrawer`

```jsx
{suggestions.length > 0 && (
  <div className="drawer-section">
    <h4>Suggested Actions</h4>
    {suggestions.map((s, i) => {
      const cfg = actionConfig(s.action);
      return (
        <div key={i} className="action-item">
          <button className={cfg.style} onClick={() => handleSuggestion(s)}>
            {cfg.label}
          </button>
          {cfg.desc && <p className="action-desc">{cfg.desc}</p>}
        </div>
      );
    })}
  </div>
)}
```

### CSS (`App.css`)

```css
.action-item { margin-bottom: 12px; }
.action-desc { margin: 4px 0 0; font-size: 0.8rem; color: #6b7280; }
.btn.danger  { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.btn.danger:hover { background: #fecaca; }
```
