# TASK-18 · Evidence Drawer — Stage 3a: Split Resolve CTA

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-16 (field diff — user can now see evidence), TASK-17 (action-oriented labels)  
**Blocks:** TASK-19, TASK-20, TASK-25  
**Can run in parallel with:** —  
**Effort:** ~2–3 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 3, item 9

---

## Background

The current `EvidenceDrawer` has a single CTA: "Resolve and capture learning". This conflates two distinct user intentions:

1. **Agreement** — User agrees with the AI suggestion and confirms it.
2. **Override** — User disagrees with the AI and makes a different decision.

Both currently generate the same learning signal, corrupting the model's feedback loop. This task splits the CTA into two distinct paths that the backend can distinguish (TASK-19 extends the backend).

---

## Acceptance Criteria

- [ ] The single "Resolve and capture learning" button is replaced with two buttons in the drawer footer:
  - **"Confirm Resolution"** — user agrees with the current status/suggestion (primary style)
  - **"Override AI"** — user wants to set a different outcome (secondary/outlined style)
- [ ] "Confirm Resolution" calls the existing resolve endpoint with an `agreement=true` signal (or a new `resolution_type: "agree"` field — coordinate with TASK-19)
- [ ] "Override AI" opens an inline override panel within the drawer (not a new modal) — for now this panel can just show a placeholder message; the full override reason capture is TASK-19
- [ ] The drawer does NOT close automatically when "Override AI" is clicked — it transitions to the override sub-view
- [ ] The drawer closes normally after "Confirm Resolution" succeeds
- [ ] Both buttons are disabled while a request is in flight

---

## Implementation Notes

### State addition in `EvidenceDrawer`

```jsx
const [overrideMode, setOverrideMode] = useState(false);
```

### Footer layout

```jsx
<div className="drawer-footer">
  {!overrideMode ? (
    <>
      <button className="btn primary" onClick={handleConfirm} disabled={loading}>
        Confirm Resolution
      </button>
      <button className="btn secondary" onClick={() => setOverrideMode(true)}>
        Override AI
      </button>
    </>
  ) : (
    // Override sub-view — placeholder until TASK-19
    <div className="override-panel">
      <p className="text-muted">Override reason capture coming in the next release.</p>
      <button className="btn link" onClick={() => setOverrideMode(false)}>← Back</button>
    </div>
  )}
</div>
```

### API call change

Pass a `resolution_type` field when confirming, so TASK-19's backend work can distinguish signals without a breaking change:

```js
api.resolve(item.id, { status: resolvedStatus, resolution_type: 'agree' })
```

The backend can ignore `resolution_type` until TASK-19 implements it.
