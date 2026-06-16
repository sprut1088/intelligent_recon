# TASK-24 · Evidence Drawer — Stage 5b: Keyboard Shortcuts

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-23 (filterable navigation — shortcuts must target the filtered set, not the raw list)  
**Blocks:** —  
**Can run in parallel with:** TASK-25  
**Effort:** ~1–2 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 5, item 15

---

## Background

Power users triaging high-volume batches (hundreds of exceptions) spend most of their time moving between items and taking the same action repeatedly. Keyboard shortcuts eliminate the click-drag overhead and cut review time significantly.

Depends on TASK-23 because the `←` / `→` shortcuts must navigate the filtered set, and the `O` shortcut maps to the Override path added in TASK-18.

---

## Acceptance Criteria

| Shortcut | Action |
|---|---|
| `←` | Navigate to previous item in filtered set |
| `→` | Navigate to next item in filtered set |
| `Escape` | Close the drawer |
| `R` | Trigger "Confirm Resolution" (equivalent to clicking the primary CTA) |
| `O` | Open Override mode (equivalent to clicking "Override AI") |
| `S` | Skip — advance to next without resolving (same as `→`) |

- [ ] Shortcuts are active **only when the drawer is open** — they must not fire when the drawer is closed (risk of accidental actions on the results table)
- [ ] Shortcuts are suppressed when focus is inside a text input or select element within the drawer (e.g., the override reason note field)
- [ ] A keyboard shortcut help legend is shown at the bottom of the drawer: `"← → navigate · R confirm · O override · Esc close"`
- [ ] The legend is dismissible (click × or a "hide shortcuts" link that persists to `localStorage`)

---

## Implementation Notes

### Event listener lifecycle

```jsx
useEffect(() => {
  if (!isOpen) return;  // only active when drawer is open

  const handler = (e) => {
    const tag = document.activeElement?.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    if (e.key === 'ArrowLeft')  { e.preventDefault(); onPrev(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); onNext(); }
    if (e.key === 'Escape')     { onClose(); }
    if (e.key === 'r' || e.key === 'R') { handleConfirm(); }
    if (e.key === 'o' || e.key === 'O') { setOverrideMode(true); }
  };

  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [isOpen, onPrev, onNext, onClose, handleConfirm]);
```

### Shortcut legend

```jsx
{!shortcutsHidden && (
  <div className="shortcut-legend">
    ← → navigate · R confirm · O override · Esc close
    <button className="btn link small" onClick={() => {
      setShortcutsHidden(true);
      localStorage.setItem('hideDrawerShortcuts', '1');
    }}>hide</button>
  </div>
)}
```

```css
.shortcut-legend { font-size: 0.75rem; color: #9ca3af; padding: 8px 22px; border-top: 1px solid #f3f4f6; display: flex; justify-content: space-between; align-items: center; }
```
