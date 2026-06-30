"""TASK-35 regression: P6 must partition by normalised counterparty.

The abc-recon-20260629 defect was that 'Batch Customer A' (sim 1.0) and 'Batch Customer B'
(sim ~0.93) both passed the old cp_threshold (0.85), so P6 subset-sum mixed PSRs from two
distinct customers into one batch group {9007,9008,9017,9018} = 4500. After TASK-35,
partitions are formed by normalised key first and the trailing-char-diff rule prevents
sibling-entity names from ever sharing a partition.
"""
from __future__ import annotations
import json
import pytest
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import (
    normalise_counterparty,
    trailing_single_char_diff,
    reconcile_transactions,
    find_one_to_many_groups,
    pattern_config,
)


P6_RULE = {
    "max_group_size": 6,
    "date_window_days": 3,
    "variance_subpass_enabled": True,
    "variance_subpass_max_group_size": 3,
    "bank_counterparty_min_similarity": 0.95,
}

SEED_PATTERNS = [
    {"pattern_id": pid, "status": "ACTIVE", "pattern_rule_json": json.dumps(rule)}
    for pid, rule in [
        ("P1", {}), ("P2", {}), ("P3", {}),
        ("P4", {"threshold": 0.85}),
        ("P5", {}),
        ("P6", P6_RULE),
        ("P7", {"minor_tolerance": 50}),
    ]
]


def _psr(tid, amount, counterparty, date="2026-06-07"):
    return PsrTransaction(tid, date, f"PMT-{tid}", amount, "CR", f"INV-{tid}",
                          counterparty, "USD", 1, "")


def _camt(ntry, amount, counterparty, date="2026-06-07"):
    return CamtTransaction(ntry, ntry, "", amount, "CR", date, date,
                           "USD", "", counterparty, "", "", {})


# ── normalise_counterparty unit tests ──────────────────────────────────────────

def test_normalise_strips_legal_suffixes():
    assert normalise_counterparty("Acme LLC") == "acme"
    assert normalise_counterparty("Acme, Inc.") == "acme"
    assert normalise_counterparty("acme") == "acme"
    assert normalise_counterparty("ACME LIMITED") == "acme"
    assert normalise_counterparty("Acme Corp") == "acme"


def test_normalise_preserves_distinct_names():
    assert normalise_counterparty("Acme") != normalise_counterparty("Acme Holdings")
    assert normalise_counterparty("Northwind Trading") != normalise_counterparty("Northwind Logistics")


def test_normalise_handles_empty():
    assert normalise_counterparty("") == ""
    assert normalise_counterparty(None) == ""  # type: ignore[arg-type]


# ── trailing_single_char_diff unit tests ───────────────────────────────────────

def test_trailing_char_diff_separates_sibling_entities():
    assert trailing_single_char_diff("batch customer a", "batch customer b") is True
    assert trailing_single_char_diff("branch 01", "branch 02") is True


def test_trailing_char_diff_ignores_unrelated_names():
    assert trailing_single_char_diff("acme", "globex") is False
    assert trailing_single_char_diff("acme holdings", "acme ventures") is False


def test_trailing_char_diff_ignores_short_or_identical():
    assert trailing_single_char_diff("ab", "ac") is False  # too short
    assert trailing_single_char_diff("acme", "acme") is False  # identical


# ── P6 partitioning behavioural tests ──────────────────────────────────────────

def test_p6_never_mixes_distinct_partitions():
    """The abc-recon scenario: two customers whose names differ by trailing letter,
    PSRs that could mathematically combine to match a bank amount → no mixed group."""
    psrs = [
        # Customer A: 1000 + 1500 + 2000 = 4500
        _psr("TX-A1", 1000.0, "Batch Customer A"),
        _psr("TX-A2", 1500.0, "Batch Customer A"),
        _psr("TX-A3", 2000.0, "Batch Customer A"),
        # Customer B: 750 + 1250 = 2000
        _psr("TX-B1", 750.0, "Batch Customer B"),
        _psr("TX-B2", 1250.0, "Batch Customer B"),
    ]
    camts = [
        _camt("NTRY-A", 4500.0, "Batch Customer A"),
        _camt("NTRY-B", 2000.0, "Batch Customer B"),
    ]
    cases = reconcile_transactions(psrs, camts, SEED_PATTERNS)

    # Two distinct group cases must form (one per customer)
    p6_cases = [c for c in cases if c.match_type == "N_TO_1"]
    assert len(p6_cases) == 2, f"Expected 2 group cases, got {len(p6_cases)}"

    # Each case must have group_role GROUP and embed the right PSR members
    grp_a_case = next(c for c in p6_cases if c.camt_id == "NTRY-A")
    grp_b_case = next(c for c in p6_cases if c.camt_id == "NTRY-B")

    assert grp_a_case.group_role == "GROUP"
    assert grp_b_case.group_role == "GROUP"
    assert grp_a_case.group_id != grp_b_case.group_id, "Must be in DIFFERENT groups"

    psr_ids_a = {m["psr_id"] for m in grp_a_case.psr_members}
    psr_ids_b = {m["psr_id"] for m in grp_b_case.psr_members}
    assert psr_ids_a == {"TX-A1", "TX-A2", "TX-A3"}, f"Customer A members wrong: {psr_ids_a}"
    assert psr_ids_b == {"TX-B1", "TX-B2"}, f"Customer B members wrong: {psr_ids_b}"


def test_p6_legal_suffix_variations_match():
    """'Acme LLC' and 'Acme Inc' normalise to the same key → can group together."""
    psrs = [
        _psr("TX-1", 100.0, "Acme LLC"),
        _psr("TX-2", 200.0, "Acme, Inc."),
        _psr("TX-3", 300.0, "ACME"),
    ]
    camts = [_camt("NTRY-1", 600.0, "Acme Corp")]
    groups = find_one_to_many_groups(psrs, camts, pattern_config(SEED_PATTERNS))
    assert len(groups) == 1
    assert {p.id for p in groups[0]["psrs"]} == {"TX-1", "TX-2", "TX-3"}


def test_p6_blocks_when_partition_key_mismatches_bank_debtor():
    """If the bank debtor name has no similar partition key, no group forms even when
    amounts subset-sum correctly."""
    psrs = [
        _psr("TX-1", 1000.0, "Northwind Trading"),
        _psr("TX-2", 1500.0, "Northwind Trading"),
    ]
    camts = [_camt("NTRY-1", 2500.0, "Globex Industries")]  # completely unrelated name
    groups = find_one_to_many_groups(psrs, camts, pattern_config(SEED_PATTERNS))
    assert groups == [], (
        f"Should not form a group across unrelated counterparties, got: "
        f"{[(g['camt'].ntry_id, [p.id for p in g['psrs']]) for g in groups]}"
    )
