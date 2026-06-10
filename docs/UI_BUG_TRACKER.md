# UI Bug & Issue Tracker

Discovered during live browser review on 2026-06-10.
Update the **Status** column as issues are worked.

Status values: `Open` | `In Progress` | `Done` | `Won't Fix`

---

## Critical Bugs

| ID | Tab | Description | Root cause | Status |
|---|---|---|---|---|
| B1 | Results Workbench | **Evidence drawer blocks sidebar nav.** Once a case row is clicked, the open drawer overlaps the left sidebar. Clicking any tab throws `intercepts pointer events`. User is stuck until drawer is manually closed. | `<aside class="drawer">` extends full viewport width / higher z-index than sidebar | Open |
| B2 | Results Workbench | **"Resolve and capture learning" button does nothing.** Button gets an active state but no `ManualResolveModal` opens. Core exception resolution workflow is broken from this entry point. | `onClick` in `EvidenceDrawer` not wired to modal state setter in `App` | Open |

---

## High Priority

| ID | Tab | Description | Root cause | Status |
|---|---|---|---|---|
| B3 | Results Workbench | **"Why this decision?" always shows "No field-level evidence stored."** `score_breakdown()` was added to the backend (`reconciliation.py`) but the drawer displays empty state for every case, including auto-closed ones. | `GET /api/reconcile/cases/{id}/explanation` either not being called or response shape mismatch in component | Open |
| B4 | Exceptions | **Exception queue shows only 5 rows out of 2,891.** Dashboards KPI correctly shows 2,891 open exceptions but the queue table shows only the 5 demo-seeded cases. No pagination controls visible. | API supports `limit`/`offset` but no pagination UI wired up in `Exceptions` component | Open |

---

## Medium Priority

| ID | Tab | Description | Root cause | Status |
|---|---|---|---|---|
| B5 | Results Workbench | **Default view shows exceptions-only.** On first load the table shows only 5 exception cases, making it look like very little data was processed. Should default to all 10,000 cases with exceptions-only unchecked. | `exceptionOnly` state initialised to `true` (or API call uses it by default) | Open |
| B6 | Results Workbench / Evidence drawer | **Suggested action confidence displays as raw decimal `0.45`** instead of a readable label like "Confidence: 45%". | No formatting applied to confidence value in `EvidenceDrawer` suggestions section | Open |
| B7 | Matching Studio | **P8 (Invoice Suffix Normalisation) shows P5's description.** Displays *"Route unresolved or low-confidence cases to manual exception handling."* which is P5's text. | Wrong fallback description returned for LEARNED pattern type in `no-code-rules` API or hardcoded in component | Open |

---

## Low Priority / Polish

| ID | Tab | Description | Root cause | Status |
|---|---|---|---|---|
| B8 | Governance | **Audit trail shows raw JSON blobs.** Each event payload is dumped verbatim in a `<code>` block. Hard to read for a client demo. | No parsing of `event_payload_json` in audit trail component | Open |

---

## Not Implemented (visible gaps, not crashes)

| ID | Tab | Feature missing | FRS Ref | Priority |
|---|---|---|---|---|
| G1 | Dashboards | No charts — all 6 panels are text bar-lists only. No bar/pie/line visualisations. | FR-VIS-01/03 | High |
| G2 | Data Intake | No way to trigger DQ validation on the pre-loaded bundled sample. "Selected batch control" shows "Upload a PSR file to create a batch." for the sample batch. | FR-ING-04 | Medium |
| G3 | Recon Copilot | Free-text input accepts anything but backend only handles 5 keyword patterns. No indication to user it's keyword-based. Returns generic catch-all for unrecognised questions. | FR-BOT-01 | Medium |
| G4 | Results Workbench | No pagination controls — only first page of results is ever visible. | FR-VIS-02 | Medium |

---

## Fix Log

| Date | ID | Change made | Author |
|---|---|---|---|
| — | — | — | — |
