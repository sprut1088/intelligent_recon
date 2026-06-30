"""TASK-36 regression: P6 prefers bank-flagged batch markers and bumps confidence.

When a CAMT entry's end_to_end_id matches a batch-marker pattern (default:
^(BATCH|BULK|CONSOL|RUN|PAYMENT[-_]?RUN)[-_]), P6 treats it as a strong hint:
- Marker-bearing CAMTs are processed FIRST so they get first refusal on PSRs
- A successful marker-seeded group earns confidence 92 (vs 88 for unflagged)
- The marker token appears in the explanation
The marker is a HINT, not a hard requirement — counterparty partition must still
align, and subset-sum must still clear.
"""
from __future__ import annotations
import json
import pytest
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import (
    is_bank_batch_marker,
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
    for pid, rule in [("P6", P6_RULE)]
]


def _patterns_with(p6_overrides):
    rule = {**P6_RULE, **p6_overrides}
    return [{"pattern_id": "P6", "status": "ACTIVE", "pattern_rule_json": json.dumps(rule)}]


def _psr(tid, amount, counterparty, date="2026-06-07"):
    return PsrTransaction(tid, date, f"PMT-{tid}", amount, "CR",
                          f"INV-{tid}", counterparty, "USD", 1, "")


def _camt(ntry, amount, counterparty, *, end_to_end="", date="2026-06-07"):
    return CamtTransaction(
        ntry_id=ntry, camt_id=ntry, end_to_end_id=end_to_end,
        amount=amount, direction="CR",
        booking_date=date, value_date=date,
        currency="USD", remittance="",
        counterparty=counterparty, pmt_ref="", invoice="", raw={},
    )


# ── is_bank_batch_marker unit tests ────────────────────────────────────────────

def test_marker_recognises_batch_prefix():
    assert is_bank_batch_marker("BATCH-GRP-A") is True
    assert is_bank_batch_marker("BATCH_RUN_2026") is True
    assert is_bank_batch_marker("BULK-PAYMENTS-001") is True
    assert is_bank_batch_marker("CONSOL-WEEK-26") is True
    assert is_bank_batch_marker("RUN-EOD-2026-06-29") is True
    assert is_bank_batch_marker("PAYMENT-RUN-001") is True
    assert is_bank_batch_marker("PAYMENT_RUN_001") is True
    assert is_bank_batch_marker("PAYMENTRUN-001") is True


def test_marker_case_insensitive():
    assert is_bank_batch_marker("batch-grp-a") is True
    assert is_bank_batch_marker("Bulk-Run-1") is True


def test_marker_rejects_non_batch_ids():
    assert is_bank_batch_marker("E2E-9001") is False
    assert is_bank_batch_marker("PMT-2026-12345") is False
    assert is_bank_batch_marker("") is False
    assert is_bank_batch_marker(None) is False  # type: ignore[arg-type]
    assert is_bank_batch_marker("BATCHIDWITHOUTSEPARATOR") is False  # needs - or _


def test_marker_custom_pattern():
    custom = r"^GROUP[-_]"
    assert is_bank_batch_marker("GROUP-A", custom) is True
    assert is_bank_batch_marker("BATCH-A", custom) is False


def test_marker_invalid_regex_falls_back_to_default():
    # Unbalanced bracket — invalid regex; helper should warn and use default
    assert is_bank_batch_marker("BATCH-GRP-A", "[invalid") is True


# ── P6 marker-seeding behavioural tests ───────────────────────────────────────

def test_marker_seeded_group_earns_higher_confidence():
    """Group with bank marker -> confidence 92, marker token in explanation."""
    psrs = [
        _psr("TX-A1", 1000.0, "Acme Holdings"),
        _psr("TX-A2", 1500.0, "Acme Holdings"),
        _psr("TX-A3", 2000.0, "Acme Holdings"),
    ]
    camts = [_camt("NTRY-1", 4500.0, "Acme Holdings", end_to_end="BATCH-GRP-A")]

    groups = find_one_to_many_groups(psrs, camts, pattern_config(SEED_PATTERNS))
    assert len(groups) == 1
    g = groups[0]
    assert g["confidence"] == 92, f"Marker-seeded group should earn 92, got {g['confidence']}"
    assert "BATCH-GRP-A" in g["explanation"]
    assert {p.id for p in g["psrs"]} == {"TX-A1", "TX-A2", "TX-A3"}


def test_unmarked_group_keeps_baseline_confidence():
    """No marker -> confidence 88 (existing baseline)."""
    psrs = [
        _psr("TX-A1", 1000.0, "Acme Holdings"),
        _psr("TX-A2", 1500.0, "Acme Holdings"),
        _psr("TX-A3", 2000.0, "Acme Holdings"),
    ]
    camts = [_camt("NTRY-1", 4500.0, "Acme Holdings", end_to_end="E2E-1234")]

    groups = find_one_to_many_groups(psrs, camts, pattern_config(SEED_PATTERNS))
    assert len(groups) == 1
    g = groups[0]
    assert g["confidence"] == 88, f"Unmarked group should stay at 88, got {g['confidence']}"
    assert "Bank flagged" not in g["explanation"]


def test_marker_with_wrong_counterparty_falls_through():
    """Marker is a hint, not an override. Wrong counterparty -> no group emitted."""
    psrs = [
        _psr("TX-A1", 1000.0, "Acme Holdings"),
        _psr("TX-A2", 1500.0, "Acme Holdings"),
        _psr("TX-A3", 2000.0, "Acme Holdings"),
    ]
    # Marker is set, but bank debtor 'Globex' doesn't match any PSR partition
    camts = [_camt("NTRY-1", 4500.0, "Globex Industries", end_to_end="BATCH-GRP-A")]

    groups = find_one_to_many_groups(psrs, camts, pattern_config(SEED_PATTERNS))
    assert groups == [], (
        "Marker hint must not bypass counterparty partition check. "
        f"Got groups: {[(g['camt'].ntry_id, [p.id for p in g['psrs']]) for g in groups]}"
    )


def test_marker_runs_before_unmarked_to_get_first_refusal():
    """Two CAMTs share an amount that could match the same PSR subset; the marker
    CAMT must claim the PSRs first."""
    psrs = [
        _psr("TX-1", 1000.0, "Acme Holdings"),
        _psr("TX-2", 1500.0, "Acme Holdings"),
    ]
    camts = [
        _camt("NTRY-NORMAL", 2500.0, "Acme Holdings", end_to_end="E2E-NORMAL"),
        _camt("NTRY-MARKER", 2500.0, "Acme Holdings", end_to_end="BATCH-GRP-XYZ"),
    ]

    groups = find_one_to_many_groups(psrs, camts, pattern_config(SEED_PATTERNS))
    # Only one of the two CAMTs can claim the PSRs; marker CAMT wins.
    assert len(groups) == 1
    assert groups[0]["camt"].ntry_id == "NTRY-MARKER", (
        f"Marker CAMT should win first refusal; got {groups[0]['camt'].ntry_id}"
    )


def test_marker_pattern_overrideable_via_config():
    """Operators can supply a custom batch_marker_regex via pattern_registry."""
    psrs = [
        _psr("TX-1", 1000.0, "Acme Holdings"),
        _psr("TX-2", 1500.0, "Acme Holdings"),
    ]
    camts = [_camt("NTRY-1", 2500.0, "Acme Holdings", end_to_end="MY-CUSTOM-MARKER")]

    cfg = pattern_config(_patterns_with({"batch_marker_regex": r"^MY[-_]CUSTOM[-_]"}))
    groups = find_one_to_many_groups(psrs, camts, cfg)
    assert len(groups) == 1
    assert groups[0]["confidence"] == 92, "Custom marker pattern should still trigger marker-seeded confidence"
    assert "MY-CUSTOM-MARKER" in groups[0]["explanation"]


def test_marker_seeded_confidence_overrideable():
    """Confidence bump value is configurable."""
    psrs = [
        _psr("TX-1", 1000.0, "Acme Holdings"),
        _psr("TX-2", 1500.0, "Acme Holdings"),
    ]
    camts = [_camt("NTRY-1", 2500.0, "Acme Holdings", end_to_end="BATCH-GRP-A")]

    cfg = pattern_config(_patterns_with({"marker_seeded_confidence": 95}))
    groups = find_one_to_many_groups(psrs, camts, cfg)
    assert len(groups) == 1
    assert groups[0]["confidence"] == 95
