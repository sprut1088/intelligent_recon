# Build Guide

## Target architecture

```text
React UI
  -> FastAPI REST API
  -> SQLite prototype store
  -> PSR/CAMT parsers
  -> Matching engine
  -> Exception workflow
  -> Human-in-the-loop learning service
  -> Pattern registry
```

For production, replace SQLite with PostgreSQL, add SSO/RBAC, use object storage for incoming files, add a queue/event stream for ingestion, and enforce maker/checker approval for learned patterns and ledger postings.

## Milestones

| Phase | Duration | Deliverable |
|---|---:|---|
| Backend data ingestion | 2 days | PSR/CAMT parser, canonical model, validation |
| Matching engine | 3 days | P1-P7 rule execution, scoring, exception outputs |
| UI workbench | 4 days | Dashboard, case table, case drawer, exceptions |
| Learning loop | 3 days | Event capture, manual resolution store, candidate patterns |
| Governance | 2 days | Pattern approval and registry |
| Demo hardening | 2 days | Test cases, scripted data, walkthrough |

## Data model highlights

- `psr_transactions`: canonical expected-payment records.
- `camt_transactions`: canonical bank-statement entries.
- `recon_cases`: reconciliation output with status, confidence, rule, and explanation.
- `recon_user_action_event`: immutable UI activity and learning signals.
- `recon_manual_resolution`: analyst-confirmed labelled training data.
- `recon_pattern_candidate`: discovered candidate patterns.
- `recon_pattern_registry`: approved seed and learned patterns.

## Next production additions

- File upload API and bank-feed scheduler.
- PostgreSQL migration scripts.
- Role-based access controls.
- Authentication and SSO.
- Full one-to-many and many-to-one solver.
- Back-testing pipeline before pattern approval.
- Ledger posting adapter with maker/checker controls.
- Audit export and retention policy.
- Synthetic regression data generator.
