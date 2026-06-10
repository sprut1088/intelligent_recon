# Developer Guide — Intelligent Recon Engine

> **Pre-reading:** Start with the [README](../README.md) for run instructions, demo flow, and key API list.
> This guide goes deeper: architecture decisions, data flows, module contracts, gap tracking, and what to build next.

---

## Table of Contents

1. [Module Map](#1-module-map)
2. [Data Flow — End to End](#2-data-flow--end-to-end)
3. [Parser Details](#3-parser-details)
4. [Reconciliation Engine — Pattern Cascade](#4-reconciliation-engine--pattern-cascade)
5. [Confidence Scoring & Decisioning](#5-confidence-scoring--decisioning)
6. [Learning Loop](#6-learning-loop)
7. [Database Schema Reference](#7-database-schema-reference)
8. [API Contract Summary](#8-api-contract-summary)
9. [Frontend Tab Map](#9-frontend-tab-map)
10. [Configuration Reference](#10-configuration-reference)
11. [FRS Gap Tracker](#11-frs-gap-tracker)
12. [Known Bugs / Edge Cases](#12-known-bugs--edge-cases)
13. [Original Build Phases](#13-original-build-phases-completed)
14. [Production Upgrade Notes](#14-production-upgrade-notes)

---

## 1. Module Map

```
backend/app/
├── config.py          — All thresholds, paths, env-var overrides (frozen dataclass)
├── db.py              — SQLite schema, connection factory, 7 seed patterns, reset helper
├── parsers.py         — PSR fixed-width parser + CAMT.053 XML parser → typed dataclasses
├── reconciliation.py  — Core matching engine: P1–P8 cascade, confidence, case builder
├── loader.py          — Orchestrates parse → DB insert → reconcile; called on startup
├── learning.py        — Mines manual resolutions → pattern candidates → approval
├── schemas.py         — Pydantic request/response models for all POST endpoints
└── main.py            — FastAPI app, all route handlers, CORS config, startup hook

frontend/src/
├── App.jsx            — Single-file SPA: all 7 tab components + state management
├── api/client.js      — Thin fetch wrapper; reads VITE_API_BASE_URL
├── App.css / styles.css
└── main.jsx
```

**Dependency order** (no circular imports):
```
config → (no deps)
db     → config
parsers → config
reconciliation → config, parsers
loader  → config, db, parsers, reconciliation
learning → config, db
main    → all of the above, schemas
```

---

## 2. Data Flow — End to End

### On startup (first run)
```
main.py: startup()
  └─ init_db()                     # creates 7 tables + seeds P1-P7 in recon_pattern_registry
  └─ load_samples_and_reconcile()  # if recon_cases table is empty
        ├─ parse_psr_file()        # → List[PsrTransaction]
        ├─ parse_camt_file()       # → List[CamtTransaction]
        ├─ INSERT psr_transactions
        ├─ INSERT camt_transactions
        ├─ SELECT recon_pattern_registry  # includes any approved learned patterns
        ├─ reconcile_transactions()       # → List[ReconCase]
        └─ INSERT recon_cases
```

### On POST /api/reconcile/run (re-run without re-parsing)
```
rerun_reconciliation_only()
  ├─ SELECT psr_transactions (already in DB)
  ├─ SELECT camt_transactions (already in DB)
  ├─ SELECT recon_pattern_registry
  ├─ reconcile_transactions()
  └─ DELETE + re-INSERT recon_cases
```

> **Key design decision:** Parsing and reconciling are separated. Re-running reconciliation
> (e.g. after approving a learned pattern) reuses parsed data — no file I/O needed.
> **Side effect:** `POST /api/load-sample` with `reset=true` also wipes all manual
> resolutions. This is a known limitation (see Section 12).

---

## 3. Parser Details

### PSR Parser (`parsers.py → parse_psr_file`)

The PSR is a fixed-width text file with three record types:

| Record | Identifier | Action |
|--------|-----------|--------|
| Header | `10` at cols 1–2 | Extracts processing date, company IBAN, currency |
| Transaction | `20` at cols 1–2 | Main parse target |
| Trailer | `99` at cols 1–2 | Skipped (not always present in sample) |

**Two-pass parsing strategy for Record 20:**

The documented field layout (100 chars) does not match the actual 10k sample file (121 chars). The parser tries a semantic regex first:

```
^20 (?P<tid>TX-\d{4}-\d+?) (?P<dt>\d{8}) (?P<rest>PMT-REF.*)$
```

This correctly handles the TX-2026-10000 overflow (13-char ID shifts all positional fields by 1). If the semantic match fails, it falls back to the documented positional layout.

**Amount scaling:** Raw 12-digit integer (e.g. `000000001001`) divided by `PSR_AMOUNT_DIVISOR` (default `1`). See [Section 10](#10-configuration-reference) and Section 12 for the open question.

**Key extracted fields per transaction:**
- `id` — Internal Treasury Transfer ID (= EndToEndId in CAMT)
- `reference` — PMT-REF-xxxxx
- `invoice` — INV-2026-xxxxx
- `counterparty` — free-text name
- `execution_date` — YYYYMMDD normalised to ISO

### CAMT.053 Parser (`parsers.py → parse_camt_file`)

Namespace-agnostic XML traversal using `tag.split("}")[-1]` so it tolerates namespace prefix variations. Iterates `<Ntry>` elements under `BkToCstmrStmt/Stmt`.

**Key extracted fields per entry:**
- `ntry_id` — `<NtryRef>` or synthetic `NTRY-{idx}` fallback
- `end_to_end_id` — `Refs/EndToEndId` (matches PSR `id`)
- `pmt_ref` — regex-extracted from `Ustrd` (`PMT-REF-\d+`)
- `invoice` — regex-extracted from `Ustrd` (`INV[-\s]?\d+...`)
- `counterparty` — `Dbtr/Nm`
- `remittance` — raw `Ustrd` content (kept for audit)
- `value_date` — currently duplicated from `booking_date` (DtTm not present in slim sample)

### Utility functions (also in parsers.py)

| Function | Purpose |
|---|---|
| `extract_pmt_ref(text)` | Regex extract `PMT-REF-\d+` from free-text |
| `extract_invoice(text)` | Regex extract `INV-\d+...` from free-text |
| `invoice_suffix(invoice)` | Returns last digit-sequence token (e.g. `"8001"` from `"INV-2026-8001"`) — used by learned P8 |
| `normalise_direction(value)` | Maps `CRDT/CREDIT/CR` → `CR`, `DBIT/DEBIT/DR` → `DR` |
| `clean_text(value)` | Collapses whitespace |
| `parse_yyyymmdd(value)` | `20260607` → `2026-06-07` |

---

## 4. Reconciliation Engine — Pattern Cascade

**Entry point:** `reconcile_transactions(psr_transactions, camt_transactions, pattern_registry_rows)`

Patterns are applied **in order**. The first match consumes both the PSR and bank entry (tracked in a `used: set` of `ntry_id` values). Lower patterns cannot re-use already-matched entries.

### Pre-built lookup indexes (built once before the loop)

```python
by_e2e      = {bank.end_to_end_id: bank}              # P1
by_ref_amt  = {(bank.pmt_ref, bank.amount): [banks]}  # P2
by_inv_amt  = {(bank.invoice, bank.amount): [banks]}   # P3
by_amt      = {bank.amount: [banks]}                   # P4 / fallback
```

### Pattern execution per PSR transaction

```
P1  EndToEndId exact match         → if amount exact: Auto-Close (conf 100)
                                   → if variance ≤ minor_tolerance: Short/Over Ledger (conf 86)
                                   → else: Exception – Amount Variance Review (conf 70)

P2  PMT-REF + amount exact         → Auto-Close (conf 96)

P3  Invoice (from Ustrd) + amount  → Auto-Close (conf 92)

P8  Learned invoice suffix + amt   → Suggested Match – Learned Pattern (conf 90)
    (only runs if an approved LEARNED pattern named "Invoice Suffix" exists)

P4  Counterparty fuzzy + amount    → Suggested Match – Analyst Review (conf = int(similarity * 100))
    (threshold: similarity ≥ 0.85 via SequenceMatcher on counterparty strings)

P5  No match found                 → Uncleared / In-Transit Payment (conf 45)
```

### After PSR loop — bank-only residuals

Any CAMT entry not consumed by the PSR loop becomes a `Bank-only Item – Investigation` (P5, conf 40).

### `build_case()` helper

Constructs a `ReconCase` dataclass with all output fields including:
- `feature_snapshot` dict — boolean flags for each match feature (used for explainability and future ML)
- `suggestions` list — proposed actions with confidence values
- `aging_days` / `aging_bucket` — computed from `value_date` vs `booking_date`

### P6 (One-to-Many) — Status: NOT EXECUTED

P6 is seeded in `recon_pattern_registry` but there is no execution logic in `reconcile_transactions`. The matching loop processes PSR transactions individually only. See [Gap #G2](#11-frs-gap-tracker).

---

## 5. Confidence Scoring & Decisioning

Confidence values are set as **constants per rule**, not computed from a weighted feature model. The `feature_snapshot` dict captures all field-agreement signals and is persisted for future use in a real scorer.

| Confidence | Resulting status | `exception_flag` |
|---|---|---|
| 100 (P1 exact) | Matched & Settled (Auto-Close) | N |
| 96 (P2) | Matched & Settled (Auto-Close) | N |
| 92 (P3) | Matched & Settled (Auto-Close) | N |
| 90 (P8 learned) | Suggested Match – Learned Pattern | Y |
| 86 (P1 + minor variance) | Post to Short or Over Ledger | Y |
| 70+ (P4 fuzzy) | Suggested Match – Analyst Review | Y |
| 70 (P1 + major variance) | Exception – Amount Variance Review | Y |
| 45 (P5 unmatched PSR) | Uncleared / In-Transit Payment | Y |
| 40 (P5 bank-only) | Bank-only Item – Investigation | Y |

Config env vars `AUTO_CLOSE_CONFIDENCE` (95) and `ASSISTED_CONFIDENCE` (80) are defined in config but not yet enforced by the engine — the engine uses hard-coded per-pattern values.

---

## 6. Learning Loop

### Full cycle

```
1. Analyst resolves exception via POST /api/reconcile/cases/{id}/resolve
      └─ Writes to: recon_user_action_event (event_type='exception_resolved')
                    recon_manual_resolution  (learning_eligible=1)
                    recon_cases              (status → 'Resolved Manually')

2. POST /api/learning/run  (or click "Discover patterns" in UI)
      └─ learning.run_learning()
            ├─ SELECT recon_manual_resolution WHERE learning_eligible=1 AND reversed_flag=0
            ├─ Group by pattern_name_for(reason_code, fields_used)
            ├─ For groups with count ≥ LEARNING_MIN_SUPPORT (default 3):
            │     └─ INSERT/UPDATE recon_pattern_candidate
            │          backtest_precision = min(98.5, 90 + support * 1.4)
            └─ Returns candidate list

3. POST /api/pattern-candidates/{id}/approve
      └─ learning.approve_candidate()
            ├─ INSERT INTO recon_pattern_registry (type='LEARNED', status='ACTIVE')
            │     pattern_id = 'P8' for Invoice Suffix, else 'PL-{short_id}'
            └─ Immediately calls rerun_reconciliation_only() so new pattern is live
```

### Pattern name → rule mapping (`learning.py`)

| Reason code / fields | Pattern name | Registry key |
|---|---|---|
| `REMITTANCE_FORMAT_MISMATCH` or `invoice_suffix` in fields | Invoice Suffix Normalisation Match | P8_LEARNED_INVOICE_SUFFIX |
| `COUNTERPARTY_ALIAS` | Counterparty Alias Learned Match | P9_COUNTERPARTY_ALIAS |
| `BANK_BATCH_AGGREGATION` | Bank Batch Settlement Grouping | P10_BANK_BATCH_GROUPING |
| `AMOUNT_VARIANCE_MINOR` | Minor Amount Variance Auto-Categorisation | PX_LEARNED |

> **Note:** P9 and P10 candidate patterns can be approved and registered, but `reconcile_transactions` only has execution logic for P8. Approving P9/P10 currently has no effect on match results.

### Demo shortcut

`POST /api/learning/demo-signals` seeds up to 5 fake `recon_manual_resolution` rows with `reason_code=REMITTANCE_FORMAT_MISMATCH` and `fields_used=["invoice_suffix","amount","counterparty_similarity"]` against real exception cases. This bypasses the analyst resolution step for demo purposes.

---

## 7. Database Schema Reference

All tables live in `backend/runtime_data/recon.db` (auto-created; gitignored).

### `psr_transactions`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | TX-2026-NNNN |
| execution_date | TEXT | ISO date |
| reference | TEXT | PMT-REF-xxxxx |
| amount | REAL | After divisor applied |
| direction | TEXT | CR / DR |
| invoice | TEXT | INV-2026-xxxxx |
| counterparty | TEXT | Free-text name |
| currency | TEXT | EUR |
| source_line | INTEGER | Line number in source file |
| raw_line | TEXT | Original line for audit |

### `camt_transactions`
| Column | Type | Notes |
|---|---|---|
| ntry_id | TEXT PK | NtryRef or NTRY-N |
| camt_id | TEXT | end_to_end_id or ntry_id |
| end_to_end_id | TEXT | Matches PSR id |
| amount | REAL | |
| direction | TEXT | CR / DR |
| booking_date | TEXT | ISO date |
| value_date | TEXT | Same as booking_date (DtTm not in sample) |
| remittance | TEXT | Raw Ustrd text |
| pmt_ref | TEXT | Extracted regex |
| invoice | TEXT | Extracted regex |
| counterparty | TEXT | Dbtr/Nm |
| raw_json | TEXT | JSON of key fields for audit |

### `recon_cases`
| Column | Type | Notes |
|---|---|---|
| case_id | TEXT PK | CASE-000001 |
| match_key | TEXT | ntry_id or psr_id |
| psr_id | TEXT | FK → psr_transactions |
| camt_id | TEXT | FK → camt_transactions |
| internal_amount | REAL | PSR amount |
| bank_amount | REAL | CAMT amount |
| variance | REAL | internal − bank |
| reconciliation_status | TEXT | See Section 4 |
| reason_code | TEXT | EXACT_MATCH, AMOUNT_MISMATCH, etc. |
| match_confidence | INTEGER | 0–100 |
| rule_applied | TEXT | P1_EXACT_END_TO_END_ID, etc. |
| exception_flag | TEXT | Y / N |
| explanation | TEXT | Plain-language rationale |
| feature_snapshot_json | TEXT | JSON of all match signals |
| suggestions_json | TEXT | JSON array of proposed actions |
| aging_days | INTEGER | |
| aging_bucket | TEXT | 0-1 Days / 2 Days / 3-5 Days / 6+ Days |

### `recon_manual_resolution`
| Column | Type | Notes |
|---|---|---|
| resolution_id | TEXT PK | RES-xxxxx |
| case_id | TEXT | FK → recon_cases |
| original_exception_type | TEXT | Status before resolution |
| final_resolution_type | TEXT | e.g. MATCHED_MANUAL |
| reason_code | TEXT | Analyst-supplied reason |
| fields_used_json | TEXT | Fields that drove the match |
| fields_ignored_json | TEXT | Fields analyst discarded |
| learning_eligible | INTEGER | 1 = feed to learner |
| reversed_flag | INTEGER | 1 = excluded from learning |

### `recon_pattern_registry`
| Column | Type | Notes |
|---|---|---|
| pattern_id | TEXT PK | P1–P7 (seed), P8+ (learned) |
| pattern_type | TEXT | SEED / LEARNED |
| status | TEXT | ACTIVE / INACTIVE |
| execution_mode | TEXT | AUTO_CLOSE / SUGGESTION / MANUAL |
| confidence_threshold | REAL | Min confidence to apply |
| pattern_rule_json | TEXT | Rule definition JSON |
| approved_by | TEXT | `system_seed` for seeds |

---

## 8. API Contract Summary

> Full interactive docs at `http://localhost:8000/docs` when the backend is running.

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/api/load-sample` | Re-parse sample files + re-reconcile. Body: `{reset: bool, amount_divisor: float}` |
| POST | `/api/reconcile/run` | Re-reconcile from DB (no file re-parse) |
| GET | `/api/reconcile/summary` | KPIs, status counts, pattern breakdown |
| GET | `/api/reconcile/cases` | Paginated cases. Query: `status`, `exception_only`, `search`, `limit`, `offset` |
| GET | `/api/reconcile/cases/{id}` | Single case + events + resolutions |
| POST | `/api/reconcile/cases/{id}/resolve` | Analyst resolution. Body: `CaseResolveRequest` |
| POST | `/api/reconcile/events` | Capture ad-hoc UI events |
| GET | `/api/events` | Paginated event log |
| GET | `/api/patterns` | All pattern registry entries |
| GET | `/api/pattern-candidates` | All candidate patterns |
| POST | `/api/learning/demo-signals` | Seed fake resolution signals |
| POST | `/api/learning/run` | Run learning analysis → produce/update candidates |
| POST | `/api/pattern-candidates/{id}/approve` | Approve candidate → add to registry → re-reconcile |
| GET | `/api/assistant/query` | Keyword copilot. Query param: `question` |

### `CaseResolveRequest` schema
```json
{
  "resolution_type": "MATCHED_MANUAL",
  "reason_code": "REMITTANCE_FORMAT_MISMATCH",
  "selected_psr_ids": ["TX-2026-0042"],
  "selected_bank_ids": ["NTRY-42"],
  "fields_used": ["invoice_suffix", "amount", "counterparty_similarity"],
  "fields_ignored": ["exact_invoice_format"],
  "accepted_variance": 0,
  "comment": "Bank drops year prefix from invoice ref",
  "final_user_confidence": "confirmed",
  "learning_eligible": true
}
```

---

## 9. Frontend Tab Map

All UI state lives in `App.jsx`. There is no router — tabs are rendered conditionally on `activeTab` state.

| Tab key | Component | API calls made | Key interactions |
|---|---|---|---|
| `command` | `CommandCentre` | `GET /summary`, `GET /cases` (counts) | Load Sample, Run Reconciliation |
| `workbench` | `Workbench` | `GET /cases` | Search, paginate, click case → detail panel |
| `exceptions` | `Exceptions` | `GET /cases?exception_only=true` | Click case → resolve modal |
| `learning` | `Learning` | `GET /pattern-candidates`, `GET /events` | Seed demo, Discover patterns, Approve |
| `patterns` | `PatternRegistry` | `GET /patterns` | Read-only view |
| `assistant` | `Assistant` | `GET /assistant/query?question=...` | Ask question, preset quick queries |
| `audit` | `AuditTrail` | `GET /events` | Read-only event log |

**Resolve flow (Exceptions tab):**
1. Click row → `ResolveModal` opens with the case pre-populated
2. Analyst fills reason code + fields used
3. `POST /api/reconcile/cases/{id}/resolve` fires
4. On success: summary and cases refresh; modal closes

---

## 10. Configuration Reference

All values are in `backend/app/config.py` as a frozen dataclass. All are overridable by environment variable.

| Env var | Default | Effect |
|---|---|---|
| `PSR_AMOUNT_DIVISOR` | `1` | Divide raw PSR integer amount by this. Set to `100` if file uses 2 implied decimals |
| `EXACT_AMOUNT_TOLERANCE` | `0.0001` | Float epsilon for "exact" amount equality |
| `MINOR_VARIANCE_TOLERANCE` | `50` | Max EUR variance auto-posted to short/over ledger (P7) |
| `AUTO_CLOSE_CONFIDENCE` | `95` | Defined but not yet enforced in engine (engine uses per-pattern hard-coded values) |
| `ASSISTED_CONFIDENCE` | `80` | Defined but not yet enforced |
| `LEARNING_MIN_SUPPORT` | `3` | Min manual resolutions before a pattern candidate is proposed |
| `IN_TRANSIT_DAYS` | `3` | Hardcoded expected clearing days attached to P5 in-transit cases |

---

## 11. FRS Gap Tracker

Priority: **H** = High (FRS Must / key demo differentiator) | **M** = Medium (FRS Should) | **L** = Low (FRS Could / out of prototype scope)

| ID | Gap | FRS Ref | Priority | Status |
|---|---|---|---|---|
| G1 | **Predictive in-transit clearing** — `IN_TRANSIT_DAYS` is a constant; no per-counterparty clearing probability, no predicted date, no "likely to self-clear vs genuine break" separation | FR-PRD-01–04 / D2 | H | ❌ Not built |
| G2 | **P6 one-to-many execution** — pattern exists in registry but `reconcile_transactions` only processes PSR lines individually; no sum-of-PSR vs single-bank-entry logic | FR-MAT-04 / P6 | H | ❌ Not built |
| G3 | **Short/over ledger allocation records** — status `"Post to Short or Over Ledger"` is produced but no simulated posting record / ledger entry is written | FR-LDG-01 / FR-EXC-02 | H | ❌ Not built |
| G4 | **CSV / Excel export** — no downloadable reconciliation report per run from UI or API | FR-RPT-01 / FR-XAI-03 | H | ❌ Not built |
| G5 | **File integrity validation** — no record-count check, no control-total validation, no quarantine on malformed input | FR-ING-04 | H | ❌ Not built |
| G6 | **LLM / NER fallback for Ustrd parsing** — only regex; messy free-text remittances that don't match `PMT-REF-\d+` or `INV-\d+` patterns will miss references | FR-CLN-03 / D4 | M | ❌ Not built |
| G7 | **P9 / P10 learned pattern execution** — can be approved into registry but reconciliation engine has no execution branch for counterparty alias or batch grouping patterns | FR-MAT-06 | M | ❌ Not built |
| G8 | **Idempotent reload** — `POST /api/load-sample` with `reset=true` deletes all manual resolutions and learning signals; a production reload should preserve analyst work | FR-ING-06 | M | ❌ Not built |
| G9 | **Auto-reverse suspense** — no mechanism to detect a previously short/over-ledger case has been offset by a later CAMT cycle and clear it | FR-LDG-02 | M | ❌ Not built |
| G10 | **Counterparty alias applied at enrichment** — learned aliases are not fed back into P4 fuzzy matching to raise its score for known aliases | FR-CDM-03 | M | ❌ Not built |
| G11 | **Confidence bands enforced from config** — `AUTO_CLOSE_CONFIDENCE` and `ASSISTED_CONFIDENCE` env vars are read but the engine uses hard-coded per-pattern values | FR-CNF-02 | M | ⚠️ Partial |
| G12 | **Filter by aging bucket / amount range / counterparty** — `/api/reconcile/cases` only supports `status`, `search`, `exception_only` | FR-VIS-04 | M | ⚠️ Partial |
| G13 | **Pattern library versioning / audit** — `recon_pattern_registry` has no version history; no log of changes to existing patterns | FR-LRN-04 | M | ❌ Not built |
| G14 | **In-transit pipeline chart** — no visualisation of in-transit items with predicted clearing dates | FR-VIS-03 | M | ❌ Not built |
| G15 | **LLM-backed copilot** — current assistant is `if/elif` keyword matching, not a real LLM with tool-calling | FR-BOT-01 / D5 | L | ⚠️ Stubbed |
| G16 | **CR/DR direction cross-validation** — direction is normalised but never validated against amount sign | FR-CLN-06 | L | ❌ Not built |
| G17 | **GL-ready posting instructions** — out of prototype scope per FRS | FR-LDG-03 | L | Won't do (prototype) |

### Gap completion checklist

- [ ] G1 — Predictive in-transit clearing
- [ ] G2 — P6 one-to-many execution
- [ ] G3 — Short/over ledger allocation records
- [ ] G4 — CSV/Excel export endpoint + UI button
- [ ] G5 — File integrity / quarantine
- [ ] G6 — LLM/NER Ustrd fallback
- [ ] G7 — P9/P10 execution branches
- [ ] G8 — Idempotent reload (preserve resolutions)
- [ ] G9 — Auto-reverse suspense on subsequent CAMT
- [ ] G10 — Counterparty alias enrichment at match time
- [ ] G11 — Enforce confidence bands from config
- [ ] G12 — Add aging/amount/counterparty filters to API + UI
- [ ] G13 — Pattern registry versioning
- [ ] G14 — In-transit pipeline chart in UI
- [ ] G15 — Replace keyword copilot with LLM + tool-calling
- [ ] G16 — Direction vs amount sign validation

---

## 12. Known Bugs / Edge Cases

| # | Description | Location | Workaround |
|---|---|---|---|
| B1 | `POST /api/load-sample` with default `reset=true` **destroys all manual resolutions and learning signals**. There is no recovery path. | `loader.py → reset_runtime_tables()` | Always use `POST /api/reconcile/run` to re-run matching without losing analyst data. Only call `/api/load-sample` when you need to reload the source files. |
| B2 | `value_date` on CAMT transactions is set to the same value as `booking_date` because the sample XML uses a flat `<Dt>` element with no separate value-date field. | `parsers.py → parse_camt_file()` | Confirm with client whether sample always has `DtTm` absent; add `ValDt` extraction if needed. |
| B3 | Amount scaling open question — PSR spec says last 2 digits are decimals (÷100) but sample answer-key reconciles as whole units. Current default is `PSR_AMOUNT_DIVISOR=1`. | `config.py` / `README.md` | Confirmed with FRS Section 6.5. Await client confirmation before changing default. |
| B4 | Confidence thresholds in `config.py` (`AUTO_CLOSE_CONFIDENCE=95`, `ASSISTED_CONFIDENCE=80`) are defined but not read by the reconciliation engine. All confidence values are hard-coded per pattern. | `reconciliation.py` | Gap G11. The config values are placeholders for a future feature. |
| B5 | The `invoice_suffix` function on an invoice like `INV-2026-8001` returns only `"8001"`. If two different invoices share the same numeric suffix (e.g. `INV-2025-8001` and `INV-2026-8001`), P8 would produce a false match. | `parsers.py → invoice_suffix()` | Low risk with the current sample; monitor when data volumes increase. |
| B6 | The assistant endpoint (`GET /api/assistant/query`) calls `summary()` internally on every request, which runs 8 SQL queries. Under load this is unnecessary. | `main.py → assistant_query()` | Acceptable for prototype; cache summary in production. |

---

## 13. Original Build Phases (completed)

For reference — the phases in which the prototype was assembled:

| Phase | Approx effort | Deliverable |
|---|---|---|
| Backend data ingestion | 2 days | PSR/CAMT parser, canonical model |
| Matching engine | 3 days | P1–P7 rule execution, scoring, exception outputs |
| UI workbench | 4 days | Dashboard, case table, case drawer, exceptions |
| Learning loop | 3 days | Event capture, manual resolution store, candidate patterns |
| Governance | 2 days | Pattern approval and registry |
| Demo hardening | 2 days | Test cases, scripted data, walkthrough |

---

## 14. Production Upgrade Notes

These are explicitly out of prototype scope per the FRS but recorded here for handover.

| Area | Change required |
|---|---|
| **Database** | Replace SQLite with PostgreSQL. Add indexes on `recon_cases(reconciliation_status, exception_flag, match_confidence)`. Add FK constraints with ON DELETE behaviour defined. |
| **File ingestion** | Add watched-folder / SFTP listener or webhook. Implement idempotent load keyed on `source_file_id` + `record natural key`. Add file quarantine store for failed validation. |
| **Real-time path** | Move to event-on-arrival (Kafka / SQS) from current batch-on-request model. |
| **Auth / RBAC** | Add OAuth2 / OIDC. Separate roles: analyst (resolve), lead (approve patterns), controller (view only), admin (load/configure). |
| **LLM copilot** | Replace `assistant_query()` keyword matching with an LLM + tool-calling agent (Azure OpenAI / Bedrock per client data-egress policy). Ground answers in live API calls. |
| **Predictive clearing** | Build per-counterparty clearing-lag model using confirmed match history from `recon_manual_resolution`. Start with median/percentile heuristic; upgrade to survival/gradient-boosted once labelled history is available (link to Solution 1 outputs). |
| **Pattern governance** | Add maker/checker workflow for pattern approval. Add version history table. Add back-test pipeline that runs a candidate against historical data before promotion. |
| **Ledger posting** | Add GL posting adapter (SAP / Oracle target TBC). Implement suspense auto-reversal on next CAMT cycle. Add maker/checker for postings. |
| **Observability** | Add OpenTelemetry traces and metrics. Key metrics: match rate per run, exception volume, learning signal accumulation rate, clearing lag p50/p95. |
| **Security** | No secrets in code (already true). Add TLS. Mask PII in logs. Confirm data-residency constraints before any external LLM call. |
