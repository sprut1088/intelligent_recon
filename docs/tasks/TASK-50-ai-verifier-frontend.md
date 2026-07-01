# TASK-50 · Frontend — AI Verifier trigger and annotation display

**Type:** Frontend  
**Branch:** `feat/ai-exception-verifier`  
**Depends on:** TASK-49 (backend endpoint and `ai_verification` field must exist)  
**Blocks:** —  
**Effort:** ~3–4 hours

---

## Background

After TASK-49, exception cases carry an `ai_verification` annotation inside
`feature_snapshot_json`. This task surfaces that annotation in the UI at two levels:

1. **ResultTable** — a small icon on each verified exception row so the analyst can
   immediately see AI's opinion while scanning the queue (green tick = agree,
   amber warning = caution, red X = disagree)

2. **EvidenceDrawer** — a dedicated "AI Verification" panel showing the full verdict,
   confidence score, and the LLM's one-sentence note

A new **"Verify exceptions"** button in the Results Workbench toolbar triggers the
`POST /api/reconcile/ai-verify` endpoint and then refreshes the table.

---

## Acceptance Criteria

- [ ] `api.aiVerify()` function added to `frontend/src/api/client.js`
- [ ] **"Verify exceptions"** button added to ResultsWorkbench toolbar, alongside the
      existing "Run AI triage" button
- [ ] Button is disabled while request is in flight; shows success toast on completion
- [ ] **ResultTable**: exception-status rows display a small verdict icon next to the
      status badge when `feature_snapshot.ai_verification` is present:
  - 🟢 `AGREE` — green checkmark
  - 🟡 `CAUTION` — amber warning triangle
  - 🔴 `DISAGREE` — red cross
- [ ] **EvidenceDrawer**: a new "AI Verification" panel renders when
      `item.feature_snapshot?.ai_verification` is present, showing:
  - Verdict badge (coloured, text: "AI: Agree" / "AI: Caution" / "AI: Disagree")
  - Confidence percentage
  - The LLM's one-sentence note
  - A subtle disclaimer: "AI second opinion on rule-proposed match — does not change status"
- [ ] Panel does not appear for non-exception cases or cases not yet verified

---

## Files to Change

| File | Change |
|---|---|
| `frontend/src/api/client.js` | Add `aiVerify()` function |
| `frontend/src/App.jsx` | Toolbar button + ResultTable icon + EvidenceDrawer panel |

---

## Implementation

### Step 1 — `frontend/src/api/client.js`

Add alongside `aiTriage`:
```js
aiVerify: (caseIds = null) => request('/api/reconcile/ai-verify', {
  method: 'POST',
  body: JSON.stringify(caseIds ? { case_ids: caseIds } : {}),
}),
```

### Step 2 — Toolbar button in `ResultsWorkbench`

Add after the existing "Run AI triage" button:

```jsx
<button
  className="btn secondary"
  disabled={loading}
  onClick={onAiVerify}
  title="Run AI second-opinion pass on P4/P7 exception cases"
>
  Verify exceptions
</button>
```

Wire `onAiVerify` in the parent `App` component:

```jsx
const runAiVerify = async () => {
  await safe(async () => {
    const result = await api.aiVerify();
    await refreshResults();
    return result;
  }, `Verification complete — ${result?.verified_count ?? 0} cases annotated`);
};
```

### Step 3 — Verdict icon in `ResultTable`

In the result row cell that renders status badges, add an inline verdict icon for rows that
have `ai_verification` data:

```jsx
{(() => {
  const v = r.feature_snapshot?.ai_verification?.verdict;
  if (!v) return null;
  const map = {
    AGREE:    { icon: '✓', cls: 'verdict-agree',    title: 'AI agrees with this match' },
    CAUTION:  { icon: '⚠', cls: 'verdict-caution',  title: 'AI has concerns about this match' },
    DISAGREE: { icon: '✗', cls: 'verdict-disagree', title: 'AI disagrees with this match' },
  };
  const m = map[v];
  return m ? <span className={`verdict-icon ${m.cls}`} title={m.title}>{m.icon}</span> : null;
})()}
```

### Step 4 — AI Verification panel in `EvidenceDrawer`

Add above or below the "Why this decision?" panel, gated on the presence of
`ai_verification`:

```jsx
{item.feature_snapshot?.ai_verification && (() => {
  const v = item.feature_snapshot.ai_verification;
  const cls = { AGREE: 'verify-agree', CAUTION: 'verify-caution', DISAGREE: 'verify-disagree' }[v.verdict] || '';
  const label = { AGREE: 'AI: Agree', CAUTION: 'AI: Caution', DISAGREE: 'AI: Disagree' }[v.verdict] || v.verdict;
  return (
    <Panel title="AI Verification" className="nested-panel">
      <div className={`ai-verify-verdict ${cls}`}>
        <span className="ai-verify-badge">{label}</span>
        <span className="ai-verify-conf">{v.confidence_pct}% confidence</span>
      </div>
      <p className="ai-verify-note">{v.note}</p>
      <p className="ai-verify-disclaimer">
        AI second opinion on rule-proposed match — does not change case status
      </p>
    </Panel>
  );
})()}
```

---

## CSS to Add in `App.css`

```css
/* Verdict icons in ResultTable */
.verdict-icon { display: inline-block; margin-left: 5px; font-size: 0.75rem; font-weight: 700; padding: 1px 4px; border-radius: 3px; }
.verdict-agree    { background: #dcfce7; color: #15803d; }
.verdict-caution  { background: #fef9c3; color: #a16207; }
.verdict-disagree { background: #fee2e2; color: #b91c1c; }

/* AI Verification panel in EvidenceDrawer */
.ai-verify-verdict { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.ai-verify-badge { font-size: 0.78rem; font-weight: 700; padding: 3px 8px; border-radius: 5px; }
.verify-agree    .ai-verify-badge { background: #dcfce7; color: #15803d; }
.verify-caution  .ai-verify-badge { background: #fef9c3; color: #a16207; }
.verify-disagree .ai-verify-badge { background: #fee2e2; color: #b91c1c; }
.ai-verify-conf { font-size: 0.78rem; color: #64748b; }
.ai-verify-note { font-size: 0.83rem; color: #1e293b; margin: 4px 0; }
.ai-verify-disclaimer { font-size: 0.72rem; color: #94a3b8; margin: 0; font-style: italic; }
```

---

## Verification

1. Run reconcile → ensure P4 / P7 exception cases exist
2. Click "Verify exceptions" button → toast confirms N cases annotated
3. Scan ResultTable — P4/P7 rows now show green/amber/red verdict icon alongside status badge
4. Open a P4 case with `AGREE` verdict in EvidenceDrawer → "AI Verification" panel shows
   green badge, confidence, and one-sentence note
5. Open a P4 case with `CAUTION` verdict → amber panel with caution note
6. Confirm that `reconciliation_status` is unchanged — deterministic rule result preserved
7. A standard matched case (no `ai_verification`) shows no verdict icon or panel
