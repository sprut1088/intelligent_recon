# Intelligent Recon Engine - FastAPI + React Prototype

This repository is a from-scratch prototype for the Solution 2 real-time reconciliation requirement. It uses the provided sample PSR fixed-width file, CAMT.053 XML bank statement, and detailed reconciliation CSV as starter data.

## Included capabilities

- FastAPI backend with SQLite runtime store.
- PSR parser for fixed-width Record Type 10/20/99 structures.
- CAMT.053 parser for ISO 20022 bank statement entries.
- Matching engine implementing the seven seed patterns:
  - P1 Exact EndToEndId match
  - P2 PMT-REF + amount
  - P3 Invoice from CAMT Ustrd + amount
  - P4 Counterparty fuzzy + amount
  - P5 Exception handling / unmatched
  - P6 One-to-many placeholder pattern in registry
  - P7 Amount variance classification
- Human-in-the-loop event capture and manual-resolution learning.
- Candidate-pattern discovery and approval workflow.
- React/Vite UI for dashboard, workbench, exceptions, learning inbox, and pattern registry.

## Local run

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8090 
# Or if getting  Program 'uvicorn.exe' failed to run: This program is blocked by group policy.
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8090
```

FastAPI docs: `http://localhost:8090/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

React UI: `http://localhost:8181`

The UI assumes the backend is running at `http://localhost:8090`. To override:

```bash
VITE_API_BASE_URL=http://localhost:8090 npm run dev
```

### Docker

```bash
docker compose up --build
```

Backend: `http://localhost:8090`
Frontend: `http://localhost:8181`

## Prototype demo flow

1. Open the dashboard and confirm PSR, CAMT, auto-match, and exception KPIs.
2. Open Recon Workbench to review cases, rule outputs, confidence, and explanation.
3. Open Exceptions and resolve a few `NO_ACCEPTABLE_CANDIDATES` cases with reason `REMITTANCE_FORMAT_MISMATCH` and fields `invoice_suffix, amount, counterparty_similarity`.
4. Open Pattern Learning and click **Run learner**.
5. Review the proposed candidate pattern, usually `Invoice Suffix Normalisation Match`.
6. Approve it as `SUGGESTION` mode.
7. Rerun reconciliation and review learned-pattern suggestions.

For a fast demo, click **Seed demo signals** in Pattern Learning, then **Run learner**, then approve the candidate.

## Important configuration

The client brief states that PSR amounts have two implied decimals, but the uploaded 10k PSR sample and detailed report align to displayed whole units. The backend therefore defaults to:

```bash
PSR_AMOUNT_DIVISOR=1
```

For production files using two implied decimals, set:

```bash
PSR_AMOUNT_DIVISOR=100
```

## Key APIs

```text
# Reconciliation
GET  /health
POST /api/load-sample
POST /api/reconcile/run
POST /api/reconcile/ai-triage
GET  /api/reconcile/summary
GET  /api/reconcile/cases
GET  /api/reconcile/cases/{case_id}
GET  /api/reconcile/cases/{case_id}/explanation
POST /api/reconcile/cases/{case_id}/resolve
POST /api/reconcile/events
GET  /api/events

# File ingestion & data quality
POST /api/files/upload
GET  /api/files/batches
GET  /api/files/batches/{batch_id}
POST /api/files/batches/{batch_id}/run
POST /api/data-quality/batches/{batch_id}/validate
GET  /api/data-quality/batches/{batch_id}

# Workspace
GET  /api/workspace/overview
GET  /api/workspace/submissions
GET  /api/workspace/data-preview
GET  /api/workspace/match-field-predictions
GET  /api/workspace/no-code-rules
GET  /api/workspace/workflow-rules
GET  /api/workspace/dashboard
POST /api/workspace/snapshot
GET  /api/workspace/export/reconciliation-results

# Exception workflow
GET  /api/exceptions/workflow
GET  /api/exceptions/{case_id}/workflow
PATCH /api/exceptions/{case_id}/workflow

# Patterns & learning
GET  /api/patterns
POST /api/patterns
PATCH /api/patterns/{pattern_id}
POST /api/patterns/{pattern_id}/activate
POST /api/patterns/{pattern_id}/deactivate
GET  /api/pattern-candidates
POST /api/learning/demo-signals
POST /api/learning/run
POST /api/pattern-candidates/{candidate_id}/approve

# Copilot
GET  /api/assistant/query
```

## Build note

This is intentionally not a black-box AI implementation. The base matching engine is deterministic and explainable. The learning component analyses repeated manual resolutions and proposes governed patterns that must be approved before they become active.

## Developer documentation

See [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) for a deeper reference covering module architecture, data flows, parser internals, the full API contract, database schema, FRS gap tracker, known bugs, and production upgrade notes.
