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


# ── Shared fixtures ────────────────────────────────────────────────────────────

P6_RULE = {
    "counterparty_threshold": 0.85,
    "max_group_size": 6,
    "date_window_days": 3,
    "variance_subpass_enabled": True,
    "variance_subpass_max_group_size": 3,
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
    {"pattern_id": "P6", "pattern_name": "One-to-Many Bank Settlement", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "SUGGESTION", "confidence_threshold": 0.85,
     "pattern_rule_json": json.dumps(P6_RULE)},
    {"pattern_id": "P7", "pattern_name": "Amount Variance", "pattern_type": "SEED",
     "status": "ACTIVE", "execution_mode": "LEDGER_OR_IN_TRANSIT", "confidence_threshold": 0.75,
     "pattern_rule_json": json.dumps({"minor_tolerance": 50})},
]


def make_psr(tid, amount, date="2026-06-01", counterparty="Crestwood Retail",
             direction="CR"):
    return PsrTransaction(tid, date, "PMT-REF-001", amount, direction, "",
                          counterparty, "EUR", 1, "")


def make_camt(ntry_id, amount, date="2026-06-01", counterparty="Crestwood Retail",
              direction="CR", e2e=""):
    return CamtTransaction(ntry_id, ntry_id, e2e, amount, direction, date, date,
                           "EUR", "batch payment", counterparty, "", "", {})


# ── Test 1: Happy path — unambiguous exact-sum group ──────────────────────────

def test_p6_happy_path_two_psrs_one_camt():
    """300 + 400 = 700 → one unambiguous P6 group (confidence 88)."""
    psrs  = [make_psr("TX-1", 300.0), make_psr("TX-2", 400.0), make_psr("TX-3", 100.0)]
    camts = [make_camt("NTRY-1", 700.0)]
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 1
    g = groups[0]
    assert g["confidence"] == 88
    assert g["rule_applied"] == "P6_BANK_BATCH_GROUPING"
    assert not g["ambiguous"]
    assert {p.id for p in g["psrs"]} == {"TX-1", "TX-2"}
    assert g["group_variance"] == 0.0
    assert g["anchor_psr"].id == "TX-1"  # earliest date / lowest id


def test_p6_anchor_is_earliest_date():
    """Anchor must be earliest execution_date; tiebreak by psr_id asc."""
    psrs = [
        make_psr("TX-B", 200.0, date="2026-06-02"),
        make_psr("TX-A", 300.0, date="2026-06-01"),
    ]
    camts = [make_camt("NTRY-1", 500.0)]
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 1
    assert groups[0]["anchor_psr"].id == "TX-A"  # earlier date


# ── Test 2: Ambiguous — two distinct valid groupings ──────────────────────────

def test_p6_ambiguous_multiple_valid_groupings():
    """TX-A+TX-B = 1000, TX-C+TX-D = 1000 against one CAMT → ambiguous (confidence 72)."""
    psrs = [
        make_psr("TX-A", 500.0), make_psr("TX-B", 500.0),
        make_psr("TX-C", 300.0), make_psr("TX-D", 700.0),
    ]
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
    """300 + 320 = 620, CAMT = 600 → variance +20 within €50 tolerance (confidence 78)."""
    psrs  = [make_psr("TX-P", 300.0), make_psr("TX-Q", 320.0)]
    camts = [make_camt("NTRY-V", 600.0)]
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 1
    g = groups[0]
    assert g["rule_applied"] == "P6_BATCH_MINOR_VARIANCE"
    assert g["confidence"] == 78
    assert abs(g["group_variance"]) <= 50


def test_p6_variance_subpass_exceeds_tolerance():
    """300 + 420 = 720, CAMT = 600 → variance +120 exceeds €50 → no group."""
    psrs  = [make_psr("TX-P", 300.0), make_psr("TX-Q", 420.0)]
    camts = [make_camt("NTRY-V", 600.0)]
    config = pattern_config(SEED_PATTERNS)

    groups = find_one_to_many_groups(psrs, camts, config)

    assert len(groups) == 0


# ── Test 4: No matching subset ────────────────────────────────────────────────

def test_p6_no_group_when_amounts_dont_sum():
    """111.11 + 222.22 = 333.33, CAMT = 999.99 → no group."""
    psrs  = [make_psr("TX-M", 111.11), make_psr("TX-N", 222.22)]
    camts = [make_camt("NTRY-Z", 999.99)]
    config = pattern_config(SEED_PATTERNS)

    assert find_one_to_many_groups(psrs, camts, config) == []


# ── Test 5: P1 isolation — P6 must not reclaim P1-matched PSRs ───────────────

def test_p6_does_not_steal_p1_matched_psrs():
    """P1 claims TX-E via exact E2E. TX-F+TX-G=500 are grouped by P6. TX-H stays P5."""
    p1_psr = PsrTransaction("TX-E", "2026-06-01", "PMT-REF-E", 500.0, "CR",
                             "INV-E", "Acme Corp", "EUR", 1, "")
    p6_psr1 = make_psr("TX-F", 200.0, counterparty="Acme Corp")
    p6_psr2 = make_psr("TX-G", 300.0, counterparty="Acme Corp")
    p5_psr  = make_psr("TX-H", 999.99, counterparty="Acme Corp")

    p1_camt = CamtTransaction("NTRY-E", "TX-E", "TX-E", 500.0, "CR",
                               "2026-06-01", "2026-06-01", "EUR", "", "Acme Corp", "", "", {})
    p6_camt = make_camt("NTRY-FG", 500.0, counterparty="Acme Corp")

    cases = reconcile_transactions([p1_psr, p6_psr1, p6_psr2, p5_psr],
                                   [p1_camt, p6_camt], SEED_PATTERNS)

    p1_cases = [c for c in cases if c.rule_applied == "P1_EXACT_END_TO_END_ID"]
    p6_cases = [c for c in cases if c.match_type == "N_TO_1"]
    p5_cases = [c for c in cases if c.rule_applied == "P5_EXCEPTION_HANDLING"
                and c.match_type == "UNMATCHED_PSR"]

    assert len(p1_cases) == 1 and p1_cases[0].psr_id == "TX-E"
    assert len(p6_cases) == 1, f"Expected 1 consolidated P6 case, got {len(p6_cases)}"
    assert len(p5_cases) == 1 and p5_cases[0].psr_id == "TX-H"

    group_case = p6_cases[0]
    assert group_case.group_role == "GROUP"
    assert group_case.group_id.startswith("GRP-")

    # Group sum = 200 + 300 = 500; bank amount = CAMT amount; variance = 0
    assert abs(group_case.internal_amount - 500.0) < 0.01
    assert group_case.bank_amount == 500.0
    assert abs(group_case.variance) < 0.01

    # Both PSRs embedded in psr_members with correct individual amounts
    assert group_case.psr_members is not None
    assert len(group_case.psr_members) == 2
    member_amounts = {m["psr_id"]: m["amount"] for m in group_case.psr_members}
    assert set(member_amounts.keys()) == {"TX-F", "TX-G"}
    assert member_amounts["TX-F"] in (200.0, 300.0)
    assert member_amounts["TX-G"] in (200.0, 300.0)


# ── Test 6: Resolve routing — member case_id → anchor ────────────────────────

def test_p6_resolve_group_case(tmp_path, monkeypatch):
    """Resolving a group case writes one resolution row with all PSR IDs and learning_eligible=0."""
    from app import config as cfg_module
    from app.config import Settings
    db_path = tmp_path / "test_p6.db"
    test_settings = Settings(database_path=db_path)
    monkeypatch.setattr(cfg_module, "settings", test_settings)

    import app.db as db_mod
    import app.reconciliation as recon_mod
    import app.loader as loader_mod
    monkeypatch.setattr(db_mod, "settings", test_settings)
    monkeypatch.setattr(recon_mod, "settings", test_settings)
    monkeypatch.setattr(loader_mod, "settings", test_settings)

    from app.db import init_db, get_conn, rows_to_dicts
    init_db()

    psrs  = [make_psr("TX-R1", 400.0), make_psr("TX-R2", 600.0)]
    camts = [make_camt("NTRY-R", 1000.0)]
    cases = reconcile_transactions(psrs, camts, SEED_PATTERNS)

    from app.reconciliation import case_to_db_tuple
    from app.loader import CASE_INSERT_SQL
    with get_conn() as conn:
        conn.executemany(CASE_INSERT_SQL, [case_to_db_tuple(c) for c in cases])
        conn.commit()

    p6_cases = [c for c in cases if c.match_type == "N_TO_1"]
    assert len(p6_cases) == 1, f"Expected 1 group case, got {len(p6_cases)}"
    group_case = p6_cases[0]
    assert group_case.group_role == "GROUP"

    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)

    resp = client.post(
        f"/api/reconcile/cases/{group_case.case_id}/resolve",
        json={
            "resolution_type": "MATCHED_MANUAL",
            "reason_code": "BANK_BATCH_AGGREGATION",
            "selected_psr_ids": [],
            "selected_bank_ids": [],
            "fields_used": ["amount_sum", "counterparty"],
            "fields_ignored": [],
            "accepted_variance": 0,
            "comment": "Test group resolve",
            "learning_eligible": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["group_id"] == group_case.group_id

    with get_conn() as conn:
        row = conn.execute(
            "SELECT reconciliation_status FROM recon_cases WHERE case_id = ?",
            (group_case.case_id,),
        ).fetchone()
    assert row["reconciliation_status"] == "Resolved Manually"

    with get_conn() as conn:
        resolutions = conn.execute(
            "SELECT * FROM recon_manual_resolution WHERE case_id = ?",
            (group_case.case_id,),
        ).fetchall()
    assert len(resolutions) == 1
    psr_ids_in_res = json.loads(resolutions[0]["psr_transaction_ids_json"])
    assert set(psr_ids_in_res) == {"TX-R1", "TX-R2"}
    assert resolutions[0]["learning_eligible"] == 0  # P6 engine suggestion
