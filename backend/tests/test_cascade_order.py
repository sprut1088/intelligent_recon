"""TASK-34 regression: P6 must run before P4 so batch members are not stolen by fuzzy 1-to-1.

Mirrors the abc-recon-20260629 defect: TX-2026-9009 (Batch Customer A, 2000 USD, member of
BATCH-GRP-A) was misrouted by P4 to NTRY-USD-016 (Batch Customer B, 2000 USD) because the
counterparty fuzzy similarity is ~0.94 and the amounts coincidentally match. After the
cascade re-order, P6 must claim TX-9009 first as a MEMBER of the GRP-A group.
"""
from __future__ import annotations
import json
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import reconcile_transactions


P6_RULE = {
    "counterparty_threshold": 0.85,
    "max_group_size": 6,
    "date_window_days": 3,
    "variance_subpass_enabled": True,
    "variance_subpass_max_group_size": 3,
}

SEED_PATTERNS = [
    {"pattern_id": "P1", "status": "ACTIVE", "pattern_rule_json": json.dumps({})},
    {"pattern_id": "P2", "status": "ACTIVE", "pattern_rule_json": json.dumps({})},
    {"pattern_id": "P3", "status": "ACTIVE", "pattern_rule_json": json.dumps({})},
    {"pattern_id": "P4", "status": "ACTIVE",
     "pattern_rule_json": json.dumps({"threshold": 0.85})},
    {"pattern_id": "P5", "status": "ACTIVE", "pattern_rule_json": json.dumps({})},
    {"pattern_id": "P6", "status": "ACTIVE", "pattern_rule_json": json.dumps(P6_RULE)},
    {"pattern_id": "P7", "status": "ACTIVE",
     "pattern_rule_json": json.dumps({"minor_tolerance": 50})},
]


def _psr(tid: str, amount: float, counterparty: str, invoice: str, ref: str,
         date: str = "2026-06-07") -> PsrTransaction:
    return PsrTransaction(tid, date, ref, amount, "CR", invoice, counterparty,
                          "USD", 1, "")


def _camt(ntry: str, amount: float, counterparty: str, e2e: str = "",
          date: str = "2026-06-07") -> CamtTransaction:
    return CamtTransaction(ntry, ntry, e2e, amount, "CR", date, date,
                           "USD", "", counterparty, "", "", {})


def test_p4_does_not_cannibalise_p6_batch_member():
    """The abc-recon defect: P4 grabs 9009 before P6 can form GRP-A."""
    psrs = [
        _psr("TX-9007", 1000.0, "Batch Customer A", "INV-3007", "PMT-91007"),
        _psr("TX-9008", 1500.0, "Batch Customer A", "INV-3008", "PMT-91008"),
        _psr("TX-9009", 2000.0, "Batch Customer A", "INV-3009", "PMT-91009"),
    ]
    camts = [
        _camt("NTRY-007", 4500.0, "Batch Customer A", e2e="BATCH-GRP-A"),
        _camt("NTRY-016", 2000.0, "Batch Customer B", e2e="BATCH-GRP-B"),  # P4 trap
    ]
    cases = reconcile_transactions(psrs, camts, SEED_PATTERNS)

    by_psr = {c.psr_id: c for c in cases if c.psr_id}

    # All three PSRs must land in the P6 group, not the P4 trap.
    assert by_psr["TX-9009"].rule_applied.startswith("P6_"), (
        f"TX-9009 should be a P6 member but got rule={by_psr['TX-9009'].rule_applied}, "
        f"camt_id={by_psr['TX-9009'].camt_id}"
    )
    assert by_psr["TX-9009"].match_type == "N_TO_1"
    assert by_psr["TX-9009"].group_role in {"ANCHOR", "MEMBER"}

    # All three PSRs share the same group_id.
    group_ids = {by_psr[t].group_id for t in ("TX-9007", "TX-9008", "TX-9009")}
    assert len(group_ids) == 1 and None not in group_ids, (
        f"All three PSRs should be in one group, got group_ids={group_ids}"
    )

    # NTRY-016 was never matched by P4 — it should appear as a bank-only item.
    bank_only = [c for c in cases if c.match_type == "UNMATCHED_BANK"]
    assert any(c.match_key == "NTRY-016" for c in bank_only), (
        "NTRY-016 should be bank-only (no P4 fuzzy steal)"
    )

    # No P4 case should exist at all in this fixture.
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert p4_cases == [], f"Unexpected P4 matches: {[(c.psr_id, c.camt_id) for c in p4_cases]}"


def test_p4_still_fires_when_no_p6_group_exists():
    """P4 must still work for genuine fuzzy 1-to-1 matches with no P6 ambiguity."""
    psrs = [
        _psr("TX-100", 775.0, "Northwind Trading Company", "INV-100", "PMT-100"),
    ]
    camts = [
        _camt("NTRY-100", 775.0, "Northwind Trading Co."),
    ]
    cases = reconcile_transactions(psrs, camts, SEED_PATTERNS)

    assert len(cases) == 1
    assert cases[0].rule_applied == "P4_COUNTERPARTY_FUZZY"
    assert cases[0].psr_id == "TX-100"
    assert cases[0].camt_id == "NTRY-100"
