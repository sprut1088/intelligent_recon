# TASK-07 · Frontend — Pre-fill Resolve modal with AI suggestion

**Type:** Frontend  
**Branch:** `feature/residual-match-ai`  
**Depends on:** TASK-05 (AI triage button + data flowing), TASK-06 (AI badge visible)  
**Blocks:** Nothing — final frontend task in the chain  
**Effort:** ~2–3 hours

---

## Background

When an analyst opens an exception case that has an AI suggestion in its `suggestions` JSON, the Resolve modal should pre-fill the resolution type and reason code based on the AI recommendation. This removes manual guesswork and makes the human confirmation step faster.

The existing `ManualResolveModal` already has `reason`, `resolutionType`, and `comment` state — the only change is initialising these from the AI suggestion when one is present, rather than always using the hardcoded defaults.

**Core principle:** The analyst still sees all fields and can change them. AI pre-fills; human confirms.

---

## Acceptance Criteria

- [ ] When a case with `suggested_action: "CONFIRM_AI_MATCH"` is opened for resolution, the modal pre-fills:
  - Resolution type → `"MATCHED_MANUAL"` (analyst confirms the AI match)
  - Reason code → `"AI_ASSISTED_MATCH"`
  - Comment → a generated string including the AI reason and confidence score
- [ ] When a case has `suggested_action: "ROUTE_TO_ANALYST"`, the modal pre-fills resolution type as `"MATCHED_MANUAL"` but comment includes a note that LLM confidence was low
- [ ] Pre-filled values are editable — the analyst can change any field before submitting
- [ ] Cases with no AI suggestion continue to use the existing default values (no regression)
- [ ] A visible label `"AI pre-filled"` or similar appears near the pre-filled fields so the analyst knows the source

---

## Implementation

### Step 1 — Locate `ManualResolveModal` in `App.jsx`

Find the component definition and its state initialisations:
```jsx
const [reason, setReason] = useState('REMITTANCE_FORMAT_MISMATCH');
const [resolutionType, setResolutionType] = useState('MATCHED_MANUAL');
const [comment, setComment] = useState('Analyst confirmed this case...');
```

### Step 2 — Extract AI suggestion from the case

The `exceptionItem` prop contains the full case record. The `suggestions_json` / `suggestions` field holds the AI data. Add a helper near the top of the component:

```jsx
function ManualResolveModal({ exceptionItem, onClose, onSubmit }) {
  // Extract AI suggestion if present
  const suggestions = exceptionItem?.suggestions || [];
  const aiSuggestion = suggestions.find(s =>
    s.action === 'CONFIRM_AI_MATCH' || s.action === 'ROUTE_TO_ANALYST'
  );
  const isAiPreFilled = !!aiSuggestion;

  const defaultReason = aiSuggestion ? 'AI_ASSISTED_MATCH' : 'REMITTANCE_FORMAT_MISMATCH';
  const defaultComment = aiSuggestion
    ? `AI triage suggested this match (confidence ${Math.round((aiSuggestion.confidence || 0) * 100)}%). ` +
      `${exceptionItem.explanation || ''} Analyst reviewed and confirmed.`
    : 'Analyst confirmed this case after checking invoice, amount and counterparty evidence.';

  const [reason, setReason] = useState(defaultReason);
  const [resolutionType, setResolutionType] = useState('MATCHED_MANUAL');
  const [comment, setComment] = useState(defaultComment);
  // ... rest of existing state unchanged
```

### Step 3 — Add `"AI_ASSISTED_MATCH"` to reason code dropdown

In the reason code `<select>`, add the new option:
```jsx
<option value="AI_ASSISTED_MATCH">AI-assisted match (analyst confirmed)</option>
```

Place it as the first option when `isAiPreFilled` is true so it is selected by default.

### Step 4 — Add "AI pre-filled" indicator label

In the modal JSX, add a small label near the top when `isAiPreFilled`:
```jsx
{isAiPreFilled && (
  <div className="eyebrow" style={{ color: '#7c3aed', marginBottom: '8px' }}>
    ✦ AI pre-filled · review before confirming
  </div>
)}
```

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/App.jsx` | Update `ManualResolveModal` to extract AI suggestion, conditionally pre-fill `reason` and `comment` state, add new `"AI_ASSISTED_MATCH"` option to reason dropdown, add AI indicator label |

---

## Notes

- `useState(defaultReason)` initialises from the AI suggestion on first render. If the user changes the reason dropdown and then opens a different case, the state resets correctly because each modal mount is fresh.
- The `exceptionItem.explanation` string is the human-readable text already stored by the AI triage endpoint — it contains the cosine score and matched text snippets.
- No backend change is required — the AI suggestion data is already in `suggestions_json` on the case record.
