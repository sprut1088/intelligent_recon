# TASK-47 · Frontend — AI candidate alternatives panel in EvidenceDrawer

**Type:** Frontend  
**Branch:** `feat/ai-candidate-picker`  
**Depends on:** TASK-46 (enriched `candidates_reviewed` must exist in `feature_snapshot_json`)  
**Blocks:** —  
**Can run in parallel with:** TASK-48  
**Effort:** ~3–4 hours

---

## Background

After Tier 2c runs, the LLM picks one CAMT as its top suggestion — but up to 5 candidates
were evaluated. Currently, the analyst can only see the LLM's chosen match; the alternatives
are buried in `feature_snapshot_json.candidates_reviewed` and never surfaced in the UI.

This task adds a collapsible "AI reviewed N candidates" panel to the EvidenceDrawer for all
AI-status cases. Each candidate row shows identifying fields and a **"Use this"** button that
pre-fills the Resolve modal exactly like the existing AI pre-fill from TASK-07 does.

This is especially important for `"AI Confirmed — No Match"` cases: the LLM said "no
confident match" but still evaluated candidates — the analyst may spot the correct one and
should be able to act on it without going fully manual.

---

## Acceptance Criteria

- [ ] A "AI considered N candidates" section appears in EvidenceDrawer for all cases
      where `item.feature_snapshot?.candidates_reviewed?.length > 0`
- [ ] Section is **collapsed by default** — analyst expands it when curious
- [ ] Each candidate row displays: CAMT ID, Amount, Date, Counterparty, Domain score (%)
- [ ] Each candidate row has a **"Use this"** button
- [ ] Clicking "Use this" pre-fills the Resolve modal with that candidate's `camt_id`,
      populating the CAMT reference field and marking the resolution as analyst-chosen override
- [ ] The currently LLM-selected candidate (matches `item.camt_id`) is visually highlighted
      (e.g. subtle green tint + "LLM pick" label) so the analyst knows which one AI chose
- [ ] Works for all three AI statuses: `AI-Assisted Suggested Match`,
      `AI - Analyst Adjudication Required`, `AI Confirmed — No Match`
- [ ] No backend changes required — reads from the existing case payload

---

## Files to Change

| File | Change |
|---|---|
| `frontend/src/App.jsx` | New collapsible candidates panel inside `EvidenceDrawer` |

---

## Implementation

### Where to add in `EvidenceDrawer`

Add the new panel after the existing "Why this decision?" `<Panel>` block and before the
"Suggested actions" panel. It should only render when the case has AI-status and
`candidates_reviewed` is populated:

```jsx
{(() => {
  const candidates = item.feature_snapshot?.candidates_reviewed;
  if (!candidates?.length) return null;
  const isAiCase = (item.reconciliation_status || '').startsWith('AI');
  if (!isAiCase) return null;
  return (
    <AiCandidatesPanel
      candidates={candidates}
      activeCamtId={item.camt_id}
      onUseCandidate={(camt_id) => {
        /* pre-fill resolve modal with this camt_id */
        setOverrideMode(true);
        // populate overrideNote with candidate info
      }}
    />
  );
})()}
```

### New `AiCandidatesPanel` component

Define above `EvidenceDrawer`:

```jsx
function AiCandidatesPanel({ candidates, activeCamtId, onUseCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const fmt = (v) => (v == null || v === '') ? '—' : String(v);
  return (
    <div className="ai-candidates-panel">
      <button
        className="ai-candidates-toggle"
        onClick={() => setExpanded(e => !e)}
      >
        {expanded ? '▾' : '▸'} AI considered {candidates.length} candidate{candidates.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <table className="ai-candidates-table">
          <thead>
            <tr>
              <th>CAMT ID</th>
              <th>Counterparty</th>
              <th>Amount</th>
              <th>Date</th>
              <th>Score</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c, i) => {
              const isActive = c.camt_id === activeCamtId;
              return (
                <tr key={c.camt_id || i} className={isActive ? 'ai-candidate-active' : ''}>
                  <td>{fmt(c.camt_id)}{isActive && <span className="ai-pick-label">LLM pick</span>}</td>
                  <td>{fmt(c.counterparty)}</td>
                  <td>{c.amount != null ? Number(c.amount).toFixed(2) : '—'}</td>
                  <td>{fmt(c.date)}</td>
                  <td>{c.domain_score != null ? `${Math.round(c.domain_score * 100)}%` : '—'}</td>
                  <td>
                    <button
                      className="btn-xs"
                      onClick={() => onUseCandidate(c)}
                    >
                      Use this
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

### "Use this" pre-fill logic

When the analyst clicks "Use this", the resolve modal should open pre-filled. Reuse the
same pre-fill pattern from TASK-07:

```js
onUseCandidate={(c) => {
  setOverrideMode(true);
  setOverrideReason('ai_candidate_override');
  setOverrideNote(
    `Analyst selected CAMT ${c.camt_id} (score ${Math.round((c.domain_score||0)*100)}%) ` +
    `over AI top pick. Counterparty: ${c.counterparty || '—'}.`
  );
  // Also pass the chosen camt_id so resolve endpoint records it
  // Store in component state: setChosenCamtOverride(c.camt_id)
}}
```

The resolve payload should include the chosen `camt_id` so the backend can record which
CAMT was ultimately linked. This requires a small addition to the override resolve payload
(pass `camt_id` in the request body to `PATCH /api/reconcile/cases/{id}/resolve`).

---

## CSS to Add in `App.css`

```css
.ai-candidates-panel { margin: 12px 0; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
.ai-candidates-toggle { width: 100%; text-align: left; background: #f8fafc; border: none; padding: 8px 12px; font-size: 0.82rem; font-weight: 600; color: #475569; cursor: pointer; }
.ai-candidates-toggle:hover { background: #f1f5f9; }
.ai-candidates-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.ai-candidates-table th, .ai-candidates-table td { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }
.ai-candidates-table thead th { background: #f8fafc; font-size: 0.72rem; text-transform: uppercase; color: #94a3b8; }
.ai-candidate-active td { background: #f0fdf4; }
.ai-pick-label { margin-left: 6px; font-size: 0.68rem; background: #dcfce7; color: #15803d; padding: 1px 5px; border-radius: 4px; font-weight: 600; }
.btn-xs { font-size: 0.75rem; padding: 3px 8px; background: #6366f1; color: white; border: none; border-radius: 4px; cursor: pointer; }
.btn-xs:hover { background: #4f46e5; }
```

---

## Verification

1. Run full reconcile + AI triage (with a valid LLM API key)
2. Open an `AI-Assisted Suggested Match` case in the EvidenceDrawer
3. Click "AI considered N candidates" toggle — table expands
4. The LLM-picked CAMT row has green tint and "LLM pick" label
5. Click "Use this" on a different candidate — Resolve modal opens pre-filled with that candidate's info
6. Repeat with an `AI Confirmed — No Match` case — candidates should still be visible and selectable
