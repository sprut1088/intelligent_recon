# TASK-32 · Tests — P6 one-to-many fixtures and test cases

**Type:** Backend (tests)  
**Branch:** `feat/one-2-many`  
**Depends on:** TASK-28 (algorithm wired), TASK-29 (resolve endpoint updated)  
**Blocks:** Nothing  
**Can run in parallel with:** TASK-31  
**Effort:** ~3–4 hours

---

## Background

Four test scenarios from the design discussion must be covered:

1. **Happy path** — 3 PSRs sum exactly to 1 CAMT → unambiguous P6 group (confidence 88)
2. **Ambiguity** — two distinct PSR subsets both sum to the same CAMT amount (confidence 72)
3. **Variance sub-pass** — small group (≤3 PSRs), sum is within €50 of CAMT (confidence 78)
4. **No group** — PSR amounts don't sum to any CAMT in the residual pool → all P5

Additional:
5. **Isolation** — P6 does not consume PSRs already matched by P1–P8
6. **Resolve routing** — resolving a MEMBER case_id auto-routes to anchor; all siblings cleared

---

## Acceptance Criteria

- [ ] New file `backend/tests/test_p6_one_to_many.py` exists
- [ ] All 6 scenarios below pass
- [ ] No existing test is broken (`python -m pytest backend/tests/ -v`)
- [ ] Tests are self-contained — no dependency on the sample data files

---

## Implementation

Create `backend/tests/test_p6_one_to_many.py`:

```python
"""Tests for P6 one-to-many (N→1) bank batch settlement matching."""
from __future__ import annotations
import json
import pytest
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import (
    find_one_to_many_groups,
    reconcile_transactions,
    pattern_config,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

P6_PATTERN_ROW = {
    "pattern_id": "P6",
    "pattern_name": "One-to-Many Bank Settlement",
    "pattern_type": "SEED",
    "status": "ACTIVE",
    "execution_mode": "SUGGESTION",
    "confidence_threshold": 0.85,
    "pattern_rule_json": json.dumps({
        "counterparty_threshold": 0.85,
        "max_group_size": 6,
        "date_window_days": 3,
        "variance_subpass_enabled": True,
        "variance_subpass_max_group_size": 3,
    }),
}

SEED_PATTERNS = [
    {"pattern_id": "P1", "pattern_name": "Exact EndToEndId", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "AUTO_CLOSE", "confidence_threshold": 0.95,
     "pattern_rule_json": json.dumps({"fields": ["end_to_end_id"]})},
    {"pattern_id": "P2", "pattern_name": "PMT-REF+Amount", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "AUTO_CLOSE", "confidence_threshold": 0.92,
     "pattern_rule_json": json.dumps({"fields": ["pmt_ref", "amount"]})},
    {"pattern_id": "P3", "pattern_name": "Invoice+Amount", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "AUTO_CLOSE", "confidence_threshold": 0.90,
     "pattern_rule_json": json.dumps({"fields": ["invoice", "amount"]})},
    {"pattern_id": "P4", "pattern_name": "Counterparty Fuzzy", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "SUGGESTION", "confidence_threshold": 0.80,
     "pattern_rule_json": json.dumps({"fields": ["counterparty", "amount"], "threshold": 0.85})},
    {"pattern_id": "P5", "pattern_name": "Exception", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "MANUAL", "confidence_threshold": 0.00,
     "pattern_rule_json": json.dumps({})},
    {"pattern_id": "P7", "pattern_name": "Amount Variance", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "LEDGER_OR_IN_TRANSIT", "confidence_threshold": 0.75,
     "pattern_rule_json": json.dumps({"minor_tolerance": 50})},
    P6_PATTERN_ROW,
]


def make_psr(tid, amount, date="2026-06-01", counterparty="Crestwood Retail",
             direction="CR", invoice="", reference="PMT-REF-001"):
    return PsrTransaction(tid, date, reference, amount, direction, invoice,
                          counterparty, "EUR", 1, "")


def make_camt(ntry_id, amount, date="2026-06-01", counterparty="Crestwood Retail",
              direction="CR", e2e=""):
    return CamtTransaction(ntry_id, ntry_id, e2e, amount, direction, date, date,
                           "EUR", "batch payment", counterparty, "", "", {})


# ── Test 1: Happy path — unambiguous exact-sum group ─────────────────────────

def test_p6_happy_path_three_psrs_one_camt():
    psrs = [
        make_psr("TX-001", 300.0),
        make_psr("TX-002", 400.0),
        make_psr("TX-003", 100.0),
    ]
    camts = [make_camt("NTRY-001", 700.0)]  # TX-001 + TX-002 = 700
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 1
    g = groups[0]
    assert g["confidence"] == 88
    assert g["rule_applied"] == "P6_BANK_BATCH_GROUPING"
    assert not g["ambiguous"]
    assert len(g["psrs"]) == 2
    psr_ids = {p.id for p in g["psrs"]}
    assert psr_ids == {"TX-001", "TX-002"}
    assert g["group_variance"] == 0.0
    # anchor is earliest date / lowest id
    assert g["anchor_psr"].id == "TX-001"


# ── Test 2: Ambiguous — two valid groupings ───────────────────────────────────

def test_p6_ambiguous_two_valid_groupings():
    psrs = [
        make_psr("TX-A", 500.0),
        make_psr("TX-B", 500.0),
        make_psr("TX-C", 300.0),
        make_psr("TX-D", 700.0),
    ]
    # TX-A+TX-B = 1000, TX-C+TX-D = 1000 — two valid groupings
    camts = [make_camt("NTRY-X", 1000.0)]
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 1
    g = groups[0]
    assert g["ambiguous"] is True
    assert g["confidence"] == 72
    assert g["rule_applied"] == "P6_BANK_BATCH_GROUPING_AMBIGUOUS"
    assert g["alternative_psrs"] is not None


# ── Test 3: Variance sub-pass ─────────────────────────────────────────────────

def test_p6_variance_subpass_small_group():
    psrs = [
        make_psr("TX-P", 300.0),
        make_psr("TX-Q", 320.0),  # sum = 620, CAMT = 600 → variance = +20 (within €50)
    ]
    camts = [make_camt("NTRY-V", 600.0)]
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 1
    g = groups[0]
    assert g["rule_applied"] == "P6_BATCH_MINOR_VARIANCE"
    assert g["confidence"] == 78
    assert abs(g["group_variance"]) <= 50


# ── Test 4: No group — no matching subset ─────────────────────────────────────

def test_p6_no_group_when_no_subset_sums():
    psrs = [
        make_psr("TX-M", 111.11),
        make_psr("TX-N", 222.22),
    ]
    camts = [make_camt("NTRY-Z", 999.99)]  # no subset sums to this
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 0


# ── Test 5: P1 isolation — P6 must not reclaim P1-matched PSRs ───────────────

def test_p6_does_not_steal_p1_matched_psrs():
    """P1 claims TX-E via exact E2E match. TX-F and TX-G remain as residual.
    P6 should only try to group TX-F and TX-G, not TX-E."""
    p1_psr = PsrTransaction("TX-E", "2026-06-01", "PMT-REF-E", 500.0, "CR",
                             "INV-E", "Acme Corp", "EUR", 1, "")
    p6_psr1 = make_psr("TX-F", 200.0, counterparty="Acme Corp")
    p6_psr2 = make_psr("TX-G", 300.0, counterparty="Acme Corp")

    p1_camt = CamtTransaction("NTRY-E", "TX-E", "TX-E", 500.0, "CR",
                               "2026-06-01", "2026-06-01", "EUR", "", "Acme Corp", "", "", {})
    p6_camt = make_camt("NTRY-FG", 500.0, counterparty="Acme Corp")  # TX-F + TX-G

    cases = reconcile_transactions([p1_psr, p6_psr1, p6_psr2],
                                   [p1_camt, p6_camt], SEED_PATTERNS)

    p1_cases = [c for c in cases if c.rule_applied == "P1_EXACT_END_TO_END_ID"]
    p6_cases = [c for c in cases if c.match_type == "N_TO_1"]
    p5_cases = [c for c in cases if c.rule_applied == "P5_EXCEPTION_HANDLING"
                and c.match_type == "UNMATCHED_PSR"]

    assert len(p1_cases) == 1, "P1 should claim TX-E"
    assert p1_cases[0].psr_id == "TX-E"
    assert len(p6_cases) == 2, "P6 should create anchor + 1 member for TX-F + TX-G"
    assert len(p5_cases) == 0, "No PSRs should remain unmatched"

    anchor = next(c for c in p6_cases if c.group_role == "ANCHOR")
    assert abs(anchor.internal_amount - 500.0) < 0.01  # group sum on anchor
    assert anchor.bank_amount == 500.0
    assert abs(anchor.variance) < 0.01


# ── Test 6: Resolve routing — member → anchor ─────────────────────────────────

def test_p6_resolve_member_routes_to_anchor(tmp_path, monkeypatch):
    """Integration test: resolving a MEMBER case_id updates all group cases."""
    # Set up an isolated DB for this test
    import os
    from app import config as cfg_module
    from app.config import AppSettings
    db_path = tmp_path / "test_recon.db"
    monkeypatch.setattr(cfg_module, "settings",
                        AppSettings(database_path=db_path))

    from app.db import init_db, get_conn, rows_to_dicts
    init_db()

    # Insert minimal P6 group directly
    psrs = [make_psr("TX-R1", 400.0), make_psr("TX-R2", 600.0)]
    camts = [make_camt("NTRY-R", 1000.0)]
    cases = reconcile_transactions(psrs, camts, SEED_PATTERNS)

    from app.reconciliation import case_to_db_tuple
    from app.loader import CASE_INSERT_SQL
    with get_conn() as conn:
        conn.executemany(CASE_INSERT_SQL, [case_to_db_tuple(c) for c in cases])
        conn.commit()

    p6_cases = [c for c in cases if c.match_type == "N_TO_1"]
    assert len(p6_cases) == 2, f"Expected 2 P6 cases, got {len(p6_cases)}"

    anchor = next(c for c in p6_cases if c.group_role == "ANCHOR")
    member = next(c for c in p6_cases if c.group_role == "MEMBER")

    # Simulate resolving via the MEMBER case_id using the FastAPI test client
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)

    resp = client.post(
        f"/api/reconcile/cases/{member.case_id}/resolve",
        json={
            "resolution_type": "MATCHED_MANUAL",
            "reason_code": "BANK_BATCH_AGGREGATION",
            "selected_psr_ids": [p.id for p in psrs],
            "selected_bank_ids": ["NTRY-R"],
            "fields_used": ["amount_sum", "counterparty"],
            "fields_ignored": [],
            "accepted_variance": 0,
            "comment": "Test group resolve",
            "learning_eligible": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolved_via_anchor"] == anchor.case_id
    assert body["group_id"] is not None

    # All group cases should now be "Resolved Manually"
    with get_conn() as conn:
        updated = rows_to_dicts(conn.execute(
            "SELECT case_id, reconciliation_status FROM recon_cases WHERE group_id = ?",
            (anchor.group_id,),
        ).fetchall())
    for row in updated:
        assert row["reconciliation_status"] == "Resolved Manually", (
            f"Case {row['case_id']} not resolved: {row['reconciliation_status']}"
        )

    # One resolution record keyed to anchor
    with get_conn() as conn:
        resolutions = conn.execute(
            "SELECT * FROM recon_manual_resolution WHERE case_id = ?",
            (anchor.case_id,),
        ).fetchall()
    assert len(resolutions) == 1
    res = resolutions[0]
    psr_ids_in_res = json.loads(res["psr_transaction_ids_json"])
    assert set(psr_ids_in_res) == {"TX-R1", "TX-R2"}
    assert res["learning_eligible"] == 0   # P6 engine suggestion → not a learning signal
```

---

## Running the tests

```bash
cd backend
python -m pytest backend/tests/test_p6_one_to_many.py -v

# Full suite to check for regressions
python -m pytest backend/tests/ -v
```
