# TASK-19 · Override Reason Capture — Frontend + Backend

**Type:** Full-stack  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-18 (split CTA — override path must exist before we build it out)  
**Blocks:** TASK-20, TASK-25  
**Can run in parallel with:** TASK-21, TASK-22  
**Effort:** ~4–5 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 3, item 10

---

## Background

Once users can see the evidence (TASK-16) and choose to override the AI (TASK-18), they need a structured way to record why. That "why" is the learning signal. Without it, the learning module cannot distinguish genuine AI errors from edge-case overrides.

This task:
1. Adds an override reason dropdown in the TASK-18 override sub-view
2. Extends the backend resolve endpoint to accept and store `resolution_type` + `override_reason`
3. Ensures the learning module tags records accordingly

---

## Acceptance Criteria

### Frontend

- [ ] The override sub-view in the drawer (introduced as a placeholder in TASK-18) is replaced with a real form:
  - Dropdown: **"Reason for override"** — options:
    - `same_entity_diff_name` — Same entity, different name format
    - `known_alias` — Known counterparty alias
    - `data_entry_error` — Data entry error in source system
    - `timing_difference` — Timing difference (split settlement)
    - `other` — Other (requires free-text note)
  - Optional free-text note field (required when `other` is selected)
  - **"Submit Override"** button — disabled until a reason is selected
  - **"← Back"** link to cancel and return to normal CTA
- [ ] On submit, calls `api.resolve()` with `resolution_type: "override"` and `override_reason` + `override_note`
- [ ] After successful override, drawer closes and results refresh

### Backend

- [ ] `POST /api/reconcile/resolve` (or equivalent) accepts optional body fields: `resolution_type` (`"agree"` | `"override"`), `override_reason` (string), `override_note` (string)
- [ ] These fields are stored on `recon_cases`: add `resolution_type`, `override_reason`, `override_note` columns (migration via `ALTER TABLE` or schema version bump)
- [ ] The learning module (`learning.py` → `run_learning()`) reads `resolution_type` and excludes `override` records from the positive training signal (or tags them separately as negative feedback)
- [ ] No breaking change to existing resolve calls that omit these fields (all three are optional, default `NULL`)

---

## Implementation Notes

### DB migration

Add to `db.py` or a migration script:

```sql
ALTER TABLE recon_cases ADD COLUMN resolution_type TEXT;
ALTER TABLE recon_cases ADD COLUMN override_reason TEXT;
ALTER TABLE recon_cases ADD COLUMN override_note TEXT;
```

Run at app startup if columns don't exist (check with `PRAGMA table_info(recon_cases)`).

### Backend resolve endpoint change

```python
class ResolveRequest(BaseModel):
    status: str
    resolution_type: Optional[str] = None   # "agree" | "override"
    override_reason: Optional[str] = None
    override_note: Optional[str] = None
```

### Learning module tagging

In `learning.py`, when querying resolved cases to build training data:

```python
# Only use agreement resolutions as positive training signal
resolved = conn.execute(
    """SELECT * FROM recon_cases
       WHERE reconciliation_status = 'Matched'
         AND (resolution_type IS NULL OR resolution_type = 'agree')"""
).fetchall()
```

Override-tagged resolutions can be counted separately as a diagnostic:
```python
logger.info("Skipped %d override resolutions from learning signal", override_count)
```
