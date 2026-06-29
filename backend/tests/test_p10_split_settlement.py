"""TASK-38 regression: P10 split-settlement detection.

One PSR paid by N CAMTs. Two trigger paths:
  1. Shared PMT-REF / invoice linkage (confidence 92 default)
  2. Counterparty subset-sum within date window (confidence 86 default)

Marker text (e.g. "1 of 2") enriches the explanation but is not required.
Sibling-entity protection (TASK-35) and partition isolation still apply.
"""
from __future__ import annotations
import json
import pytest
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import (
    detect_split_marker,
    find_one_to_n_splits,
    reconcile_transactions,
    pattern_config,
)


P10_RULE_DEFAULT = {
    "max_split_size": 5,
    "date_window_days": 3,
    "bank_counterparty_min_similarity": 0.95,
    "shared_reference_confidence": 92,
    "subset_sum_confidence": 86,
}


def _patterns(p10_overrides=None, full=False):
    """Pattern registry.

    full=False -> only P10 (for isolated find_one_to_n_splits tests)
    full=True  -> P1..P7 + P10 (for full reconcile_transactions tests)
    """
    rule = {**P10_RULE_DEFAULT, **(p10_overrides or {})}
    if not full:
        return [{"pattern_id": "P10", "status": "ACTIVE", "pattern_rule_json": json.dumps(rule)}]
    base = [
        ("P1", {}), ("P2", {}), ("P3", {}),
        ("P4", {"similarity_floor": 0.92}),
        ("P5", {}),
        ("P6", {"max_group_size": 6, "date_window_days": 3,
                "bank_counterparty_min_similarity": 0.95}),
        ("P7", {"minor_tolerance": 50}),
        ("P10", rule),
    ]
    return [
        {"pattern_id": pid, "status": "ACTIVE", "pattern_rule_json": json.dumps(r)}
        for pid, r in base
    ]


def _psr(tid, amount, counterparty, *, date="2026-06-07", ref=None, invoice=None):
    return PsrTransaction(tid, date, ref or f"PMT-{tid}", amount, "CR",
                          invoice or f"INV-{tid}", counterparty, "USD", 1, "")


def _camt(ntry, amount, counterparty, *, date="2026-06-07", pmt_ref="", invoice="", remit=""):
    return CamtTransaction(
        ntry_id=ntry, camt_id=ntry, end_to_end_id="",
        amount=amount, direction="CR",
        booking_date=date, value_date=date,
        currency="USD", remittance=remit,
        counterparty=counterparty, pmt_ref=pmt_ref, invoice=invoice, raw={},
    )


# ── detect_split_marker unit tests ─────────────────────────────────────────────

def test_marker_detects_k_of_n():
    assert detect_split_marker("1 of 2") == (1, 2)
    assert detect_split_marker("Part 2 of 4") == (2, 4)
    assert detect_split_marker("payment 3/5") == (3, 5)


def test_marker_case_insensitive():
    assert detect_split_marker("1 OF 2") == (1, 2)
    assert detect_split_marker("1 Of 2") == (1, 2)


def test_marker_rejects_invalid_or_missing():
    assert detect_split_marker("") is None
    assert detect_split_marker(None) is None
    assert detect_split_marker("just text") is None
    # k > total -> invalid
    assert detect_split_marker("5 of 2") is None
    # total < 2 -> not a split
    assert detect_split_marker("1 of 1") is None


def test_marker_custom_pattern_falls_back_on_invalid():
    assert detect_split_marker("1 of 2", r"[invalid") == (1, 2)


# ── Path 1: shared-reference unit tests ────────────────────────────────────────

def test_split_via_shared_pmt_ref():
    """The abc-recon case: PSR 3300, two CAMTs share its PMT-REF and sum to 3300."""
    psrs = [_psr("TX-9010", 3300.0, "Partial Payer LLC",
                 ref="PMT-REF-91010", invoice="INV-2026-3010")]
    camts = [
        _camt("PARTIAL-A", 2000.0, "Partial Payer LLC",
              pmt_ref="PMT-REF-91010", invoice="INV-2026-3010", remit="1 of 2"),
        _camt("PARTIAL-B", 1300.0, "Partial Payer LLC",
              pmt_ref="PMT-REF-91010", invoice="INV-2026-3010", remit="2 of 2"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert len(splits) == 1
    s = splits[0]
    assert s["psr"].id == "TX-9010"
    assert {c.ntry_id for c in s["camts"]} == {"PARTIAL-A", "PARTIAL-B"}
    assert s["confidence"] == 92
    assert s["marker_detected"] is True
    assert "PMT-REF-91010" in s["explanation"]
    assert "1/2" in s["explanation"] and "2/2" in s["explanation"]


def test_split_via_shared_invoice_no_marker():
    """No 'K of N' text — still groups by shared invoice."""
    psrs = [_psr("TX-1", 1000.0, "Cust A", ref="UNRELATED-A",
                 invoice="INV-SHARED-2026")]
    camts = [
        _camt("C-1", 400.0, "Cust A", pmt_ref="REF-X", invoice="INV-SHARED-2026"),
        _camt("C-2", 600.0, "Cust A", pmt_ref="REF-Y", invoice="INV-SHARED-2026"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert len(splits) == 1
    assert splits[0]["confidence"] == 92
    assert splits[0]["marker_detected"] is False
    assert "invoice 'INV-SHARED-2026'" in splits[0]["explanation"]


def test_split_subset_sum_within_shared_reference_bucket():
    """3 CAMTs share the PSR's reference; only 2 of them sum to PSR amount."""
    psrs = [_psr("TX-1", 500.0, "Cust A", ref="PMT-CORE-2026")]
    camts = [
        _camt("C-1", 200.0, "Cust A", pmt_ref="PMT-CORE-2026"),
        _camt("C-2", 300.0, "Cust A", pmt_ref="PMT-CORE-2026"),
        _camt("C-3", 150.0, "Cust A", pmt_ref="PMT-CORE-2026"),  # red herring
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert len(splits) == 1
    assert {c.ntry_id for c in splits[0]["camts"]} == {"C-1", "C-2"}


# ── Path 2: subset-sum-on-counterparty unit tests ──────────────────────────────

def test_split_via_subset_sum_on_counterparty_no_shared_ref():
    """CAMTs have NO shared PMT-REF/invoice with the PSR; only counterparty match."""
    psrs = [_psr("TX-1", 3300.0, "Acme Holdings",
                 ref="UNRELATED-PSR-REF", invoice="UNRELATED-PSR-INV")]
    camts = [
        _camt("C-1", 2000.0, "Acme Holdings", pmt_ref="BANK-A", invoice="BANK-INV-A"),
        _camt("C-2", 1300.0, "Acme Holdings", pmt_ref="BANK-B", invoice="BANK-INV-B"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert len(splits) == 1
    assert splits[0]["confidence"] == 86
    assert splits[0]["rule_applied"] == "P10_SPLIT_SUBSET_SUM"


def test_split_blocked_by_different_counterparty():
    """No shared ref AND CAMT counterparty doesn't match PSR -> no split."""
    psrs = [_psr("TX-1", 3300.0, "Partial Payer LLC", ref="X", invoice="Y")]
    camts = [
        _camt("C-1", 2000.0, "Globex Industries", pmt_ref="A", invoice="B"),
        _camt("C-2", 1300.0, "Globex Industries", pmt_ref="C", invoice="D"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert splits == []


def test_split_blocked_by_sibling_entity_partition():
    """'Customer A' vs 'Customer B' must not bind across the trailing-char-diff guard."""
    psrs = [_psr("TX-1", 3300.0, "Batch Customer A", ref="X", invoice="Y")]
    camts = [
        _camt("C-1", 2000.0, "Batch Customer B", pmt_ref="A", invoice="B"),
        _camt("C-2", 1300.0, "Batch Customer B", pmt_ref="C", invoice="D"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert splits == []


def test_split_respects_date_window():
    """CAMTs outside ±date_window_days excluded from Path 2."""
    psrs = [_psr("TX-1", 3300.0, "Acme", date="2026-06-10")]
    camts = [
        _camt("C-1", 2000.0, "Acme", date="2026-06-25"),  # 15 days out
        _camt("C-2", 1300.0, "Acme", date="2026-06-11"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert splits == [], "Date window violation must block Path 2"


def test_split_max_size_cap():
    """max_split_size=2 should refuse a 3-CAMT split via Path 2."""
    psrs = [_psr("TX-1", 600.0, "Acme")]
    camts = [
        _camt("C-1", 100.0, "Acme"),
        _camt("C-2", 200.0, "Acme"),
        _camt("C-3", 300.0, "Acme"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns({"max_split_size": 2})))
    assert splits == []


def test_split_path1_wins_over_path2():
    """When a shared-reference split exists, Path 1 should consume it first
    (higher confidence). Path 2 should not fire for the same PSR."""
    psrs = [_psr("TX-1", 3300.0, "Acme", ref="SHARED-CORE-REF")]
    camts = [
        _camt("C-1", 2000.0, "Acme", pmt_ref="SHARED-CORE-REF"),
        _camt("C-2", 1300.0, "Acme", pmt_ref="SHARED-CORE-REF"),
    ]
    splits = find_one_to_n_splits(psrs, camts, pattern_config(_patterns()))
    assert len(splits) == 1
    assert splits[0]["rule_applied"] == "P10_SPLIT_SHARED_REFERENCE"
    assert splits[0]["confidence"] == 92


# ── Full-pipeline regression: abc-recon scenario ───────────────────────────────

def test_abc_recon_split_settlement_full_pipeline():
    """End-to-end: PSR 9010 with two PARTIAL CAMTs sharing its PMT-REF/invoice.
    Old behaviour: 1 unmatched PSR + 2 bank-only items.
    New behaviour: 1 anchor case (1_TO_N) + 1 member case, no bank-onlys."""
    psrs = [_psr("TX-2026-9010", 3300.0, "Partial Payer LLC",
                 ref="PMT-REF-91010", invoice="INV-2026-3010")]
    camts = [
        _camt("PARTIAL-9010-A", 2000.0, "Partial Payer LLC",
              pmt_ref="PMT-REF-91010", invoice="INV-2026-3010", remit="1 of 2"),
        _camt("PARTIAL-9010-B", 1300.0, "Partial Payer LLC",
              pmt_ref="PMT-REF-91010", invoice="INV-2026-3010", remit="2 of 2"),
    ]
    cases = reconcile_transactions(psrs, camts, _patterns(full=True))

    # No P5 unmatched PSR, no bank-only items
    p5_unmatched = [c for c in cases if c.rule_applied == "P5_EXCEPTION_HANDLING"]
    assert p5_unmatched == [], f"Split should consume the PSR + CAMTs; got {p5_unmatched}"

    # Exactly one 1_TO_N group, anchor + member
    split_cases = [c for c in cases if c.match_type == "1_TO_N"]
    assert len(split_cases) == 2
    assert {c.group_role for c in split_cases} == {"ANCHOR", "MEMBER"}

    anchor = next(c for c in split_cases if c.group_role == "ANCHOR")
    member = next(c for c in split_cases if c.group_role == "MEMBER")
    assert anchor.psr_id == "TX-2026-9010"
    assert member.psr_id == "TX-2026-9010"
    assert anchor.internal_amount == 3300.0
    assert anchor.bank_amount == 3300.0
    assert anchor.variance == 0.0
    assert anchor.match_confidence == 92
    assert anchor.rule_applied == "P10_SPLIT_SHARED_REFERENCE"
    assert anchor.group_id == member.group_id
    assert anchor.group_id.startswith("SPLIT-")
    # Marker text appears in the anchor explanation
    assert "1/2" in anchor.explanation and "2/2" in anchor.explanation


def test_split_does_not_steal_p1_matched_camt():
    """If a CAMT was already exact-matched by P1 (EndToEndId), P10 must not reclaim it."""
    psrs = [
        _psr("TX-EXACT", 2000.0, "Acme", ref="REF-EXACT", invoice="INV-EXACT"),
        _psr("TX-SPLIT", 3300.0, "Acme", ref="REF-SHARED", invoice="INV-SHARED"),
    ]
    camts = [
        # Will P1-match TX-EXACT via end_to_end_id
        CamtTransaction(
            ntry_id="NTRY-EXACT", camt_id="NTRY-EXACT", end_to_end_id="TX-EXACT",
            amount=2000.0, direction="CR",
            booking_date="2026-06-07", value_date="2026-06-07",
            currency="USD", remittance="",
            counterparty="Acme", pmt_ref="REF-EXACT", invoice="INV-EXACT", raw={},
        ),
        _camt("C-PART-1", 2000.0, "Acme", pmt_ref="REF-SHARED", invoice="INV-SHARED"),
        _camt("C-PART-2", 1300.0, "Acme", pmt_ref="REF-SHARED", invoice="INV-SHARED"),
    ]
    cases = reconcile_transactions(psrs, camts, _patterns(full=True))

    p1_case = next(c for c in cases if c.psr_id == "TX-EXACT")
    assert p1_case.rule_applied == "P1_EXACT_END_TO_END_ID"
    assert p1_case.camt_id == "NTRY-EXACT"

    # TX-SPLIT must still get its 2-CAMT split (C-PART-1 + C-PART-2)
    split_cases = [c for c in cases if c.psr_id == "TX-SPLIT" and c.match_type == "1_TO_N"]
    assert len(split_cases) == 2
