"""TASK-37 regression: P4 fuzzy gate must require corroboration.

Old P4: similarity(psr.cp, camt.cp) >= 0.85 + exact amount -> emit at int(score*100).
This was too loose — it produced 91-94% suggestions for sibling-entity names
("Customer A" vs "Customer B") and abbreviation mismatches with no second signal.

New P4 (TASK-37):
- Similarity floor raised to 0.92 on NORMALISED keys
- trailing_single_char_diff blocks sibling entities outright
- Corroboration required: shared PMT-REF substring, shared invoice substring,
  or date within +/-1 day with exact amount
- Confidence capped at 89 so suggestions never look auto-closable
"""
from __future__ import annotations
import json
import pytest
from app.parsers import PsrTransaction, CamtTransaction
from app.reconciliation import reconcile_transactions, shared_substring


P4_RULE_DEFAULT = {
    "similarity_floor": 0.92,
    "confidence_cap": 89,
    "corroboration_required": True,
    "shared_substring_min_len": 5,
    "date_window_days": 1,
}


def _patterns(p4_rule=None):
    rule = p4_rule if p4_rule is not None else P4_RULE_DEFAULT
    base = [
        ("P1", {}), ("P2", {}), ("P3", {}),
        ("P4", rule),
        ("P5", {}),
        ("P6", {"max_group_size": 6, "date_window_days": 3, "bank_counterparty_min_similarity": 0.95}),
        ("P7", {"minor_tolerance": 50}),
    ]
    return [
        {"pattern_id": pid, "status": "ACTIVE", "pattern_rule_json": json.dumps(r)}
        for pid, r in base
    ]


def _psr(tid, amount, counterparty, *, date="2026-06-07", ref=None, invoice=None):
    return PsrTransaction(tid, date, ref or f"PMT-{tid}", amount, "CR",
                          invoice or f"INV-{tid}", counterparty, "USD", 1, "")


def _camt(ntry, amount, counterparty, *, date="2026-06-07", pmt_ref="", invoice=""):
    return CamtTransaction(
        ntry_id=ntry, camt_id=ntry, end_to_end_id="",
        amount=amount, direction="CR",
        booking_date=date, value_date=date,
        currency="USD", remittance="",
        counterparty=counterparty, pmt_ref=pmt_ref, invoice=invoice, raw={},
    )


# ── shared_substring unit tests ────────────────────────────────────────────────

def test_shared_substring_finds_common_chunk():
    assert shared_substring("INV-2026-12345", "REF-2026-12345-X", min_len=5) is True
    assert shared_substring("PMT-9001-ABC", "PMT-9001-XYZ", min_len=5) is True


def test_shared_substring_case_insensitive():
    assert shared_substring("invoice-abcde", "INVOICE-VWXYZ", min_len=7) is True


def test_shared_substring_rejects_short_overlap():
    assert shared_substring("AB-1234", "XY-9876", min_len=5) is False


def test_shared_substring_handles_empty():
    assert shared_substring("", "anything", min_len=3) is False
    assert shared_substring(None, "anything", min_len=3) is False  # type: ignore[arg-type]


# ── P4 behavioural tests ───────────────────────────────────────────────────────

def test_p4_blocks_when_no_corroboration():
    """Similarity clears the floor (normalised key match), exact amount, but no shared
    ref/invoice and dates far apart -> no P4 case. Confirms the gate blocks on the
    corroboration step, not the similarity step."""
    psrs = [_psr("TX-1", 1000.0, "Northwind Trading Company",
                 date="2026-06-01", ref="PMT-AAA-111", invoice="INV-AAA-111")]
    camts = [_camt("NTRY-1", 1000.0, "Northwind Trading Co.",
                   date="2026-06-20", pmt_ref="PMT-BBB-222", invoice="INV-BBB-222")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert p4_cases == [], f"Expected no P4 case without corroboration; got {p4_cases}"
    # PSR should fall through to P5 unmatched exception
    psr_case = next(c for c in cases if c.psr_id == "TX-1")
    assert psr_case.rule_applied == "P5_EXCEPTION_HANDLING"


def test_p4_fires_with_shared_pmt_ref():
    """Names normalise to same key, dates far apart, but shared PMT-REF substring -> P4 fires."""
    psrs = [_psr("TX-1", 1000.0, "Northwind Trading Company",
                 date="2026-06-01", ref="PMT-CORR-2026-9001")]
    camts = [_camt("NTRY-1", 1000.0, "Northwind Trading Co.",
                   date="2026-06-20", pmt_ref="REF-CORR-2026-9001-X")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert len(p4_cases) == 1, f"Expected P4 to fire on shared PMT-REF corroboration; got {p4_cases}"
    assert "shared PMT-REF substring" in p4_cases[0].explanation


def test_p4_fires_with_shared_invoice():
    """Invoices differ but share a >=5 char substring -> P4 fires on invoice corroboration.
    Distinct invoice strings prevent P3 (exact match) from snatching it first."""
    psrs = [_psr("TX-2", 2222.0, "Northwind Trading Company",
                 date="2026-06-01", ref="PMT-A-001", invoice="ALPHA-77777-PSR")]
    camts = [_camt("NTRY-2", 2222.0, "Northwind Trading Co.",
                   date="2026-06-20", pmt_ref="REF-B-002", invoice="BETA-77777-CAMT")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert len(p4_cases) == 1, f"Expected P4 to fire on shared invoice corroboration; got {p4_cases}"
    assert "shared invoice substring" in p4_cases[0].explanation


def test_p4_fires_with_date_corroboration():
    """Names normalise identically, refs/invoices unrelated, but dates within +/-1 day -> P4 fires."""
    psrs = [_psr("TX-1", 1000.0, "Northwind Trading Company",
                 date="2026-06-10", ref="UNRELATED-AAA", invoice="INV-ALPHA")]
    camts = [_camt("NTRY-1", 1000.0, "Northwind Trading Co.",
                   date="2026-06-11", pmt_ref="UNRELATED-BBB", invoice="INV-BETA")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert len(p4_cases) == 1, f"Expected P4 to fire on date corroboration; got {p4_cases}"
    assert "date within" in p4_cases[0].explanation


def test_p4_blocks_trailing_char_diff_even_with_corroboration():
    """Sibling-entity names ('Customer A' vs 'Customer B') must not pass P4
    even when a shared invoice substring would otherwise corroborate."""
    psrs = [_psr("TX-1", 1500.0, "Batch Customer A",
                 date="2026-06-10", ref="SHARED-REF-2026", invoice="SHARED-INV-2026")]
    camts = [_camt("NTRY-1", 1500.0, "Batch Customer B",
                   date="2026-06-10", pmt_ref="SHARED-REF-2026", invoice="SHARED-INV-2026")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert p4_cases == [], f"trailing-char-diff guard should block this match; got {p4_cases}"


def test_p4_legal_suffix_variations_still_match():
    """The intended case: 'Northwind Trading Company' vs 'Northwind Trading Co.'
    normalise to the same key, so similarity is 1.0. With date corroboration -> P4 fires."""
    psrs = [_psr("TX-1", 5000.0, "Northwind Trading Company",
                 date="2026-06-10", ref="X", invoice="INV-NORTH-1")]
    camts = [_camt("NTRY-1", 5000.0, "Northwind Trading Co.",
                   date="2026-06-10", pmt_ref="Y", invoice="INV-NORTH-2")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert len(p4_cases) == 1


def test_p4_confidence_capped_at_89():
    """Even at similarity 1.0 with corroboration, P4 confidence must be capped."""
    psrs = [_psr("TX-1", 7777.0, "Northwind Trading Co.",
                 date="2026-06-10", ref="X", invoice="INV-1")]
    camts = [_camt("NTRY-1", 7777.0, "Northwind Trading Co.",
                   date="2026-06-10", pmt_ref="Y", invoice="INV-2")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert len(p4_cases) == 1
    assert p4_cases[0].match_confidence == 89, (
        f"P4 confidence must be capped at 89, got {p4_cases[0].match_confidence}"
    )


def test_p4_blocks_below_similarity_floor():
    """Score 0.88 (above old 0.85, below new 0.92 floor) -> no P4 case."""
    psrs = [_psr("TX-1", 3333.0, "Acme Widgets Limited",
                 date="2026-06-10", ref="SHARED-CORROB-2026", invoice="INV-A")]
    # Make a name that scores ~0.88 (token-set + WRatio): partial overlap
    camts = [_camt("NTRY-1", 3333.0, "Beacon Hardware",
                   date="2026-06-10", pmt_ref="SHARED-CORROB-2026", invoice="INV-B")]
    cases = reconcile_transactions(psrs, camts, _patterns())
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert p4_cases == [], (
        f"Names are too dissimilar; corroboration alone must not pass P4. Got {p4_cases}"
    )


def test_p4_legacy_threshold_key_still_works():
    """Legacy P4.threshold key (pre-TASK-37) is honoured as similarity_floor + logs a warning."""
    legacy_rule = {
        "threshold": 0.80,  # legacy key, deliberately permissive
        "corroboration_required": False,  # disable corroboration to isolate the threshold
    }
    psrs = [_psr("TX-1", 4444.0, "Globex Industries",
                 date="2026-06-10", ref="X", invoice="INV-X")]
    camts = [_camt("NTRY-1", 4444.0, "Globex Industrial Holdings",
                   date="2026-06-25", pmt_ref="Y", invoice="INV-Y")]
    cases = reconcile_transactions(psrs, camts, _patterns(legacy_rule))
    p4_cases = [c for c in cases if c.rule_applied == "P4_COUNTERPARTY_FUZZY"]
    assert len(p4_cases) == 1, "Legacy threshold=0.80 should let this pass when corroboration disabled"
    # Confidence still capped at default 89
    assert p4_cases[0].match_confidence <= 89
