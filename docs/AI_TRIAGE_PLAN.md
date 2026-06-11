# AI-Assisted Reconciliation: Two-Pass Architecture Plan

**Status:** Design agreed, implementation starting next session  
**Branch:** `dev-docs-cleanup`  
**Date drafted:** 2026-06-10  
**Revised:** 2026-06-10 — incorporated mentor review (4 design fixes, 4 future vision items added)

---

## Context — Why we need this

The current deterministic engine (P1–P8) handles ~85–90% of volume.  
The residual (~10–15%) lands in one of these buckets:

| Status | Cause | Volume in test_50 |
|---|---|---|
| Uncleared / In-Transit | No CAMT match found at all | 10 |
| Suggested Match – Analyst Review | P4 fuzzy hit between 0.85–0.99 | 3 |
| Bank-only Item | CAMT entry with no PSR counterpart | 10 |
| Exception – Amount Variance Review | P1 matched identity, amount gap > 50 | 3 |

Analysts today work this residual manually — one case at a time.  
Goal: **use AI to pre-triage the residual before it reaches the analyst queue**, without blowing out API cost or removing human control.

---

## Core Design Principle

> AI never auto-closes. It pre-fills. Humans confirm.

Every AI suggestion produces a new status `"AI-Assisted Suggested Match"` with a confidence score and a plain-English reason. The analyst clicks **Confirm** or **Reject**. Confirmations feed the learning loop → approved patterns become new deterministic rules → residual pool shrinks over time.

---

## Two-Pass Architecture

```
┌─────────────────────────────────────────────────────────┐
│  PASS 1 — Deterministic (current)                        │
│                                                           │
│  P1 E2E exact → P2 PMT-REF+amt → P3 Invoice+amt          │
│  → P8 Learned suffix → P4 Fuzzy (SequenceMatcher ≥0.85)  │
│  → P5 Unmatched                                           │
│                                                           │
│  Handles ~85-90% volume. Zero AI cost. Fully auditable.   │
└──────────────────────────┬──────────────────────────────┘
                           │ unmatched pool only
                           ▼
┌─────────────────────────────────────────────────────────┐
│  PASS 2 — AI Residual Triage (new)                       │
│                                                           │
│  2a → 2b → 2c  (only runs on records Pass 1 left behind) │
└─────────────────────────────────────────────────────────┘
```

---

## Pass 2 Tiers

### Tier 2a — Smarter Fuzzy (Free, no API, ~1 afternoon)

**Library:** `rapidfuzz` (drop-in replacement for `difflib.SequenceMatcher`)  
**Why better:** Uses token-aware algorithms — "Crestwood Retail" vs "Crestwood Retail Group" → **96** (vs 84 in SequenceMatcher which character-counts the extra word)

Algorithms to use in cascade:

| Algorithm | Score | Catches |
|---|---|---|
| `token_set_ratio` | 0–100 | Extra legal suffixes (Group, Ltd, plc, UK) |
| `partial_ratio` | 0–100 | Substring containment |
| `WRatio` | 0–100 | Combined, handles reordering |

**Change required:**  
- Add `rapidfuzz` to `backend/requirements.txt`
- In `backend/app/reconciliation.py`: replace `similarity()` function  
- Add a new P4b step (token_set_ratio ≥ 85) that runs before P5  
- P4b produces status `"Suggested Match – Enhanced Fuzzy"` with conf = token_set score

Current `similarity()` in `reconciliation.py` (line 26):
```python
# CURRENT — character-level SequenceMatcher
def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, (left or "").upper(), (right or "").upper()).ratio()
```

Proposed replacement:
```python
# NEW — token-set aware (rapidfuzz)
from rapidfuzz import fuzz as rfuzz

def similarity(left: str, right: str) -> float:
    """Primary: token_set_ratio handles entity suffixes (Ltd, plc, Group).
    Falls back to WRatio for everything else. Returns 0–1 float."""
    a = (left or "").upper()
    b = (right or "").upper()
    ts = rfuzz.token_set_ratio(a, b) / 100.0
    wr = rfuzz.WRatio(a, b) / 100.0
    return max(ts, wr)
```

**Known miss that this fixes:**  
`"Crestwood Retail"` vs `"Crestwood Retail Group"` → 0.84 → 0.96 (MATCH)

---

### Tier 2b — Embedding Similarity (Very cheap, batch)

**When:** After 2a, for records still unmatched  
**What:** Compute cosine similarity between text embeddings of unmatched PSR and CAMT records

> **⚠ Mentor fix — Embeddings are bad at math.**  
> Do NOT put amounts or dates inside the embedding string. Vector models treat `"105.00"` and `"1050.0"` as semantically similar because they share characters. Numbers must be handled deterministically *before* embeddings run.

**Correct two-step approach:**

**Step 1 — Deterministic pre-filter (guard rails, runs first):**  
For each unmatched PSR, narrow the candidate CAMT pool to records that satisfy ALL of:
- `direction` matches (CR↔CR, DR↔DR) — prevents matching a credit to a debit
- `abs(psr.amount - camt.amount) ≤ MINOR_VARIANCE_TOLERANCE` (default 50) — amount window
- `abs(date_diff) ≤ IN_TRANSIT_DAYS` (default 3) — booking date window

Only records that pass these guards enter the embedding comparison.

**Step 2 — Embedding cosine similarity on text fields only:**  
Embed only the text fields:
```
PSR text:  "{reference} {invoice} {counterparty}"
CAMT text: "{remittance} {counterparty}"
```

Proposes candidate pairs where cosine similarity ≥ 0.65.

**Model options (in cost order):**

| Option | Cost | Notes |
|---|---|---|
| `sentence-transformers all-MiniLM-L6-v2` | **Free** (local CPU) | ~50ms per 100 records. No PII leaves the server. |
| `text-embedding-3-small` (OpenAI) | $0.00002 / 1K tokens | ~$0.0004 per 1,000 unmatched |
| `text-embedding-3-large` (OpenAI) | $0.00013 / 1K tokens | Only if accuracy gap matters |

**Recommendation:** Start with `sentence-transformers` locally — no API key, no cost, no PII exposure, ships in `requirements.txt`.

New endpoint: `POST /api/reconcile/ai-triage`  
- Takes current unmatched PSR + CAMT pool from the DB  
- Step 1: deterministic pre-filter by direction + amount window + date window  
- Step 2: embeddings on text fields only → cosine similarity  
- Returns up to **Top 5 candidates per PSR** (ranked by cosine score)  
- Records in "maybe zone" (0.60–0.84) are passed to Tier 2c for LLM adjudication  
- Clear matches (≥ 0.85) stored directly as `AI_SUGGESTED` cases

---

### Tier 2c — LLM Adjudication (Targeted, cheap)

**When:** After 2b, for records in the "maybe zone" (cosine similarity 0.60–0.84)  
**What:** For each PSR, pass it to the LLM with only its **Top 5 CAMT candidates** (from Tier 2b), not the full pool

> **⚠ Mentor fix — LLM combinatorial overload.**  
> Passing 20–50 PSRs × 20–50 CAMTs in one prompt creates an N×M comparison matrix. LLMs suffer "lost in the middle" blindness on long contexts and will hallucinate pairs or miss matches. The fix: Tier 2b narrows to Top 5 candidates per PSR, then the LLM answers a focused question — *"which of these 5 is the match, and why?"*

**Prompt structure — one PSR + its Top 5 candidates:**
```
You are a reconciliation analyst. One PSR payment record is unmatched.
Review the 5 candidate CAMT bank entries below and identify the best match.

PSR:
  ID: {psr_id} | Direction: {direction} | Amount: {amount} {currency}
  Date: {execution_date} | Reference: {reference}
  Invoice: {invoice} | Counterparty: {counterparty}

CAMT Candidates (pre-filtered by amount/date/direction):
  1. {ntry_id} | Remittance: {remittance} | Party: {counterparty} | Amt: {amount} | Date: {booking_date}
  2. ...
  [up to 5]

Return valid JSON matching this schema exactly:
{
  "psr_id": "string",
  "matched_camt_id": "string or null",
  "confidence_pct": number,
  "reason": "string",
  "suggested_action": "CONFIRM_AI_MATCH | ROUTE_TO_ANALYST | NO_MATCH"
}
If no candidate is a credible match, set matched_camt_id to null.
```

> **⚠ Mentor fix — Structured outputs.**  
> Use GPT-4o-mini's JSON schema enforcement (`response_format={"type": "json_object"}`) to guarantee valid output shape. Do not rely on parsing free-text LLM responses — they will fail in production.

> **⚠ Mentor fix — Missing fields.**  
> The prompt includes `direction` (CR/DR) and `execution_date`/`booking_date`. Without these, the LLM could propose matching a January Credit to a March Debit.

**Cost at scale (10,000 PSR/day example):**

| Stage | Records remaining | Action |
|---|---|---|
| After Pass 1 | ~1,000 unmatched (10%) | |
| After 2a rapidfuzz | ~600 | Free |
| After 2b pre-filter + embeddings | ~200 in maybe-zone | Free (local model) |
| 2c LLM: 1 PSR + Top 5 per call | 200 calls | ~$0.04 total (GPT-4o-mini) |

Note: cost is slightly higher than the original N×M batching estimate but **accuracy and reliability are substantially better**.

---

## What Changes in the Codebase

### Backend

| File | Change |
|---|---|
| `requirements.txt` | Add `rapidfuzz`, `sentence-transformers` (for local embeddings) |
| `app/reconciliation.py` | Replace `similarity()` with rapidfuzz version; add P4b step |
| `app/main.py` | Add `POST /api/reconcile/ai-triage` endpoint |
| `app/ai_triage.py` | New module: embedding similarity + LLM batch logic |
| `app/db.py` | No schema change needed — `AI_SUGGESTED` is a new value for existing `reconciliation_status` column |

> **⚠ Known POC limitation — AI suggestion durability.**  
> The current rerun flow (`loader.py`, `ingestion.py`) executes `DELETE FROM recon_cases` before reinserting deterministic results. This means AI-suggested cases stored in `recon_cases` are wiped on every rerun and must be regenerated by calling `/api/reconcile/ai-triage` again.  
> **For the POC this is acceptable** — reruns are intentional resets, demo sessions are single-sitting, and rerunning triage costs ~$0.04.  
> **For production** this must be resolved with separate persistence tables (`ai_triage_run`, `ai_triage_candidate`, `ai_triage_decision`) keyed to a batch/version, so AI suggestions and analyst decisions survive reruns and accumulate a compliance-ready audit trail. Captured in FS-5 below.

### Frontend

| File | Change |
|---|---|
| `App.jsx` | Add "Run AI triage" button in Results Workbench (similar to "Run learner" in Learning Lab) |
| `App.jsx` | Show `AI_SUGGESTED` status with a distinct badge/colour in ResultTable |
| `App.jsx` | Pre-fill Resolve modal with AI suggestion when `suggestions` array contains an AI entry |
| `api/client.js` | Add `aiTriage: () => request('/api/reconcile/ai-triage', { method: 'POST' })` |

---

## New UI Status Labels

| Status | Pass | Colour | Icon |
|---|---|---|---|
| Matched & Settled (Auto-Close) | P1/P2/P3 | Green | ✓ |
| Post to Short or Over Ledger | P7 | Amber | ~ |
| Suggested Match – Analyst Review | P4 | Blue | ? |
| **Suggested Match – Enhanced Fuzzy** | **2a** | **Blue-light** | **~?** |
| **AI-Assisted Suggested Match** | **2b/2c** | **Purple** | **AI** |
| Exception – Amount Variance Review | P7 | Red | ! |
| Uncleared / In-Transit | P5 | Grey | ⏱ |
| Bank-only Item | P5 | Orange | ∅ |

---

## Self-Improving Loop

```
Pass 1 deterministic rules → unmatched pool shrinks each sprint
         │
         ▼
Pass 2 AI catches residual → analyst confirms / rejects
         │ confirms
         ▼
Learning loop (existing) → candidate pattern created
         │ approved
         ▼
New deterministic rule added to pattern registry
         │
         ▼
Pass 1 now catches what previously needed AI → AI cost drops
```

The system gets **cheaper to operate over time**, not more expensive.

---

## Future State — Vision Items

> These are not in scope for the current implementation sprint. Parked here for future roadmap discussion.

### FS-1: Counterparty Outreach Drafting (Agentic Action)
When a case is confirmed as "Bank-only Item" with missing remittance details, an LLM automatically drafts an email to the counterparty requesting the missing invoice/reference. The analyst reviews and clicks **Send** — no manual writing. Requires an email integration layer and analyst approval gate.

### FS-2: Automated Batch Root Cause Summaries
After each reconciliation run, an LLM analyses the exception distribution and produces a plain-English operations summary: *"Batch 52EF had elevated exceptions because 'Crestwood Retail' changed their payment gateway and is no longer prefixing references with PMT-"*. Massive value for Treasury operations managers who currently read raw exception counts. Feeds directly into the Dashboards tab.

### FS-3: Intelligent Entity Resolution Graph
Use the LLM over historic resolution data to build a persistent **counterparty alias graph** — discovering that *Riverside Energy*, *Riv-En PLC*, and *Riverside Gas* are the same entity. Exposing this graph to P4 in Pass 1 elevates deterministic match accuracy before AI triage is even needed, shrinking the residual pool further.

### FS-5: AI Suggestion Persistence (Production-grade durability)
Add three dedicated tables so AI results survive deterministic reruns and accumulate a decision audit trail:
- `ai_triage_run` — one row per triage execution (batch_id, model used, timestamp, cost)
- `ai_triage_candidate` — one row per PSR→CAMT suggestion (psr_id, camt_id, score, reason, tier)
- `ai_triage_decision` — one row per analyst confirm/reject (candidate_id, analyst, decision, timestamp)

`recon_cases` would reference `ai_triage_candidate_id` rather than store AI suggestions inline. This decouples the AI layer from the deterministic rerun wipe, enables cost tracking per run, and produces a compliance-ready history of every AI suggestion and its human disposition.

### FS-4: Generative Audit Explainability
Take the `feature_snapshot_json` from each deterministic auto-close and run it through a small local LLM to generate a compliance-ready audit sentence: *"Auto-closed: EndToEndId TX-2027-0001 matched exactly. Amount EUR 2,500 matched exactly. No variance. Rule P1_EXACT_END_TO_END_ID applied. Confidence 100%."* Makes regulatory audits seamless without touching the deterministic engine.

### FS-6: AI-Assisted Rule Drafting (Closing the Learning Loop with AI)

**Context:** The current learning loop is purely statistical — it counts repeated analyst resolutions and proposes a pattern candidate when the count exceeds `LEARNING_MIN_SUPPORT` (default 3). It says *"this happened 5 times"* but cannot explain *why* or draft the rule logic.

**What this adds:** After enough AI triage suggestions are confirmed by analysts, instead of only feeding the statistical learner, the confirmed feature signatures are passed to an LLM which drafts a candidate rule in plain English:

> *"Based on 5 confirmed matches where PSR invoice was 'INV-2027-XXXX' and CAMT remittance contained 'INV-XXXX' (year prefix stripped), a new deterministic rule could be: match on invoice numeric suffix + exact amount. Confidence: high. Scope: payments from 'Global Collection Svcs' only until back-tested more broadly."*

The LLM draft goes into the pattern governance inbox alongside statistical candidates. A developer reviews, encodes it as a new pattern (e.g. P9), and it enters the registry. From that point it runs in Pass 1 — no AI cost, fully deterministic.

**Why this matters:** It closes the flywheel completely. AI doesn't just match residuals — it actively proposes how to eliminate future residuals.

**What this is NOT:** AI does not auto-create or auto-activate rules. Every draft requires human review and explicit approval before entering the registry. The deterministic engine remains the source of truth.

---

## Confirmed Known Issues to Fix First

These are blocking a clean demo before we add AI triage:

| Bug | Location | Impact |
|---|---|---|
| B1 | EvidenceDrawer z-index blocks sidebar nav | High — breaks navigation |
| B2 | Resolve button in exceptions broken | High — blocks learning loop demo |
| B3 | Explainability panel shows empty | Medium — needs case data loaded first |

Fix order: B2 → B1 → B3 → then start AI triage implementation.

---

## Implementation Order for Next Session

1. **Fix B2** (resolve button) — so we can demo the learning loop end-to-end  
2. **Fix B1** (drawer z-index) — so navigation works while drawer is open  
3. **Add rapidfuzz (Tier 2a)** — highest ROI, zero cost, one afternoon  
   - `pip install rapidfuzz`
   - Replace `similarity()` in `reconciliation.py`
   - Add P4b step in the cascade
   - Verify Crestwood Retail test case now matches
4. **Add `POST /api/reconcile/ai-triage` stub** — returns hardcoded structure first, wire to embeddings after
5. **Add "Run AI triage" button** in Results Workbench UI

---

## Files to Read on Day Start

| File | Why |
|---|---|
| `backend/app/reconciliation.py` | Full P1–P8 cascade, `similarity()` location (line 26) |
| `backend/app/main.py` | All endpoints, where to add new route |
| `frontend/src/App.jsx` | `ResultsWorkbench` component, `ManualResolveModal`, `EvidenceDrawer` |
| `frontend/src/api/client.js` | API client — add `aiTriage` call here |
| `docs/DEVELOPER_GUIDE.md` | Full architecture reference |
| `docs/UI_BUG_TRACKER.md` | B1, B2, B3 bug details |
| `backend/sample_data/psr_test_50.txt` | 50-record test file (TX-2027-xxxx) |
| `backend/sample_data/camt_test_50.xml` | 50-entry CAMT test file |

---

## Test Verification After Tier 2a (rapidfuzz)

Run this to confirm the fix works:

```python
from rapidfuzz import fuzz as rfuzz

pairs = [
    ("Crestwood Retail",  "Crestwood Retail Group"),   # was MISS (0.84), should now MATCH
    ("Riverside Energy",  "Riverside Energy plc"),      # was MATCH, should stay MATCH
    ("Brightwater Ltd",   "Brightwater Limited"),       # was MATCH, should stay MATCH
    ("Shoreline Foods",   "Shoreline Foods UK"),        # was MATCH, should stay MATCH
]
for a, b in pairs:
    ts = rfuzz.token_set_ratio(a.upper(), b.upper()) / 100
    wr = rfuzz.WRatio(a.upper(), b.upper()) / 100
    score = max(ts, wr)
    print(f"{'MATCH' if score >= 0.85 else 'MISS '}  {score:.4f}  {a!r} vs {b!r}")
```

Expected: all 4 pairs → MATCH. This also raises total P4 matches in test_50 from 3 to 4.
