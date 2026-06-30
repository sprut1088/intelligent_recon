# TASK-29 · Group-aware resolve endpoint

**Type:** Backend  
**Branch:** `feat/one-2-many`  
**Depends on:** TASK-28 (P6 cases with `group_id` / `group_role` must be in DB)  
**Blocks:** TASK-31  
**Can run in parallel with:** TASK-30, TASK-32  
**Effort:** ~2–3 hours

---

## Background

When an analyst resolves a P6 group case, the existing resolve endpoint receives whichever
`case_id` the user clicked — which may be a MEMBER row, not the ANCHOR. The endpoint must:

1. **Auto-route** member case_ids to their anchor transparently
2. **Atomically** update all cases in the group to "Resolved Manually"
3. Write **one** `recon_manual_resolution` row keyed to the anchor, listing all group PSR IDs
4. Set `learning_eligible = 0` on P6-originated resolutions (the engine suggested this;
   it is not a new discovery for the learner)
5. Return an extended response that surfaces the routing and group metadata

The existing endpoint (`POST /api/reconcile/cases/{case_id}/resolve`) is extended — no new
endpoint is created.

---

## Acceptance Criteria

- [ ] Resolving an **anchor** case_id: all MEMBER cases in the same group also move to
      `"Resolved Manually"` in the same DB transaction
- [ ] Resolving a **MEMBER** case_id: handler auto-routes to anchor; response includes
      `"resolved_via_anchor"` with the anchor case_id
- [ ] Resolving a non-group case (group_role is NULL): behaviour unchanged from today
- [ ] Exactly **one** `recon_manual_resolution` row per group resolve (keyed to anchor case_id)
- [ ] `psr_transaction_ids_json` on that row contains all PSR IDs in the group
- [ ] `learning_eligible = 0` when the resolved case has `rule_applied` matching `P6_*`
- [ ] Event payload includes `"routed_from_member": true` when a member case_id was passed
- [ ] `POST /api/reconcile/cases/{member_case_id}/resolve` returns HTTP 200 (not 400/404)
- [ ] Response body extended with `"group_id"`, `"member_case_ids"`, `"resolved_via_anchor"`
      (all null/empty for non-group cases — backward-compatible)
- [ ] `python -m pytest backend/tests/ -v` passes with no regressions

---

## Implementation

### Changes to `resolve_case()` in `backend/app/main.py`

The function currently at line ~419. Replace the body with the group-aware version below.

Key changes:
- After fetching the case, check `group_role`. If MEMBER, redirect to the anchor.
- After writing the resolution, update all sibling cases atomically.
- Pass `learning_eligible = 0` when `rule_applied` starts with `"P6_"`.

```python
@app.post("/api/reconcile/cases/{case_id}/resolve")
def resolve_case(case_id: str, request: CaseResolveRequest) -> dict:
    with get_conn() as conn:
        case = conn.execute(
            "SELECT * FROM recon_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # ── Group-awareness: auto-route member → anchor ──────────────────
        routed_from_member = False
        if case["group_role"] == "MEMBER":
            anchor_row = conn.execute(
                "SELECT * FROM recon_cases WHERE group_id = ? AND group_role = 'ANCHOR'",
                (case["group_id"],),
            ).fetchone()
            if anchor_row:
                routed_from_member = True
                case = anchor_row   # resolve via anchor from here on

        # ── Collect group siblings (null if not a group case) ────────────
        group_id        = case["group_id"]
        group_case_ids  = []
        group_psr_ids   = []
        if group_id:
            sibling_rows = conn.execute(
                "SELECT case_id, psr_id FROM recon_cases WHERE group_id = ?",
                (group_id,),
            ).fetchall()
            group_case_ids = [r["case_id"] for r in sibling_rows]
            group_psr_ids  = [r["psr_id"] for r in sibling_rows if r["psr_id"]]

        # ── Determine PSR and bank IDs for the resolution record ─────────
        if group_psr_ids:
            selected_psr  = group_psr_ids                               # all PSRs in group
        else:
            selected_psr  = request.selected_psr_ids or ([case["psr_id"]] if case["psr_id"] else [])
        selected_bank = request.selected_bank_ids or ([case["camt_id"]] if case["camt_id"] else [])

        # ── Override and learning eligibility ────────────────────────────
        is_override = bool(request.override_reason)
        is_p6_case  = (case["rule_applied"] or "").startswith("P6_")
        # P6-originated: engine suggested it — not a new signal for the learner
        effective_learning_eligible = (
            False if is_override or is_p6_case else request.learning_eligible
        )
        effective_comment = request.comment
        if is_override:
            note_part = f" Note: {request.override_note}" if request.override_note else ""
            effective_comment = f"Override reason: {request.override_reason}.{note_part}"

        # ── Write event ──────────────────────────────────────────────────
        event_id      = f"EVT-{uuid.uuid4().hex[:10].upper()}"
        resolution_id = f"RES-{uuid.uuid4().hex[:10].upper()}"
        anchor_case_id = case["case_id"]

        payload = {
            "case_id":                   case_id,          # originally clicked case
            "resolved_via_anchor":       anchor_case_id if routed_from_member else None,
            "routed_from_member":        routed_from_member,
            "group_id":                  group_id,
            "resolution_type":           request.resolution_type,
            "reason_code":               request.reason_code,
            "selected_psr_ids":          selected_psr,
            "selected_bank_ids":         selected_bank,
            "fields_used":               request.fields_used,
            "fields_ignored":            request.fields_ignored,
            "accepted_variance":         request.accepted_variance,
            "comment":                   effective_comment,
            "previous_engine_confidence": case["match_confidence"],
            "final_user_confidence":     request.final_user_confidence,
            "override_reason":           request.override_reason,
            "override_note":             request.override_note,
        }
        conn.execute(
            "INSERT INTO recon_user_action_event "
            "(event_id, case_id, event_type, user_id, event_payload_json) "
            "VALUES (?, ?, 'exception_resolved', 'prototype_user', ?)",
            (event_id, anchor_case_id, json_dumps(payload)),
        )

        # ── Write single resolution row (keyed to anchor) ────────────────
        conn.execute(
            "INSERT INTO recon_manual_resolution "
            "(resolution_id, case_id, original_exception_type, final_resolution_type, "
            " reason_code, psr_transaction_ids_json, bank_transaction_ids_json, "
            " amount_variance, date_variance_days, fields_used_json, fields_ignored_json, "
            " user_comment, resolved_by, learning_eligible) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prototype_user', ?)",
            (
                resolution_id, anchor_case_id,
                case["reconciliation_status"], request.resolution_type,
                request.reason_code,
                json_dumps(selected_psr), json_dumps(selected_bank),
                request.accepted_variance if request.accepted_variance is not None else case["variance"],
                case["aging_days"],
                json_dumps(request.fields_used), json_dumps(request.fields_ignored),
                effective_comment,
                1 if effective_learning_eligible else 0,
            ),
        )

        # ── Atomically update all cases in the group ─────────────────────
        if group_case_ids:
            placeholders = ",".join("?" * len(group_case_ids))
            conn.execute(
                f"UPDATE recon_cases SET reconciliation_status='Resolved Manually', "
                f"reason_code=?, exception_flag='N', explanation=?, "
                f"updated_at=CURRENT_TIMESTAMP WHERE case_id IN ({placeholders})",
                (
                    request.reason_code,
                    f"Resolved by analyst as {request.resolution_type}. "
                    f"Learning signal {'excluded (P6 engine suggestion)' if is_p6_case else 'excluded (override)' if is_override else 'captured'}.",
                    *group_case_ids,
                ),
            )
            mark_workflow_resolved(conn, anchor_case_id, updated_by="prototype_user",
                                   comment=f"Resolved as {request.resolution_type}")
        else:
            # Non-group case — original single-case path
            conn.execute(
                "UPDATE recon_cases SET reconciliation_status='Resolved Manually', "
                "reason_code=?, exception_flag='N', explanation=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE case_id=?",
                (
                    request.reason_code,
                    f"Resolved by analyst as {request.resolution_type}. "
                    f"Learning signal {'excluded (override)' if is_override else 'captured'}.",
                    anchor_case_id,
                ),
            )
            mark_workflow_resolved(conn, anchor_case_id, updated_by="prototype_user",
                                   comment=f"Resolved as {request.resolution_type}")

        conn.commit()

    return {
        "case_id":            case_id,
        "event_id":           event_id,
        "resolution_id":      resolution_id,
        "status":             "resolved",
        "group_id":           group_id,
        "resolved_via_anchor": anchor_case_id if routed_from_member else None,
        "member_case_ids":    [c for c in group_case_ids if c != anchor_case_id] if group_case_ids else [],
    }
```

---

## Verification

```bash
cd backend
python -c "
from app.loader import load_samples_and_reconcile
load_samples_and_reconcile(reset=True)

from app.db import get_conn, rows_to_dicts

with get_conn() as conn:
    # Find a P6 anchor case
    anchor = conn.execute(
        \"SELECT * FROM recon_cases WHERE group_role='ANCHOR' LIMIT 1\"
    ).fetchone()

if not anchor:
    print('No P6 anchor cases found — test requires sample data with P6 groups.')
    print('SKIP (generate sample data with groupable transactions to test)')
else:
    print(f'Found anchor: {anchor[\"case_id\"]} group_id={anchor[\"group_id\"]}')
    # Find a member in the same group
    with get_conn() as conn:
        member = conn.execute(
            \"SELECT * FROM recon_cases WHERE group_id=? AND group_role='MEMBER' LIMIT 1\",
            (anchor['group_id'],)
        ).fetchone()
    print(f'Found member: {member[\"case_id\"]}')
    print('Resolve via member case_id — should auto-route to anchor')
"

python -m pytest backend/tests/ -v
```
