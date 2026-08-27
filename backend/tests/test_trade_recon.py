"""Tests for trade reconciliation (FIX vs CCF)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers import parse_fix_file, parse_ccf_file, FixTransaction, CcfTransaction
from app.trade_reconciliation import reconcile_trades

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent


class TestFixParser:
    def test_parse_sample(self):
        txns = parse_fix_file(FIXTURE_DIR / "front_office_exec.fix")
        assert len(txns) == 99
        # Tag 37 -> FO Order ID (trade_id); Tag 17 -> ExecutionID (exec_id, primary key)
        assert txns[0].trade_id == "ORD20260001"
        assert txns[0].exec_id == "EXE10000001"
        assert txns[0].isin == "US5949181045"
        assert txns[0].side == "BUY"
        assert txns[0].quantity == 2500.0
        assert txns[4].side == "SELL"

    def test_fields_complete(self):
        txns = parse_fix_file(FIXTURE_DIR / "front_office_exec.fix")
        for t in txns:
            assert t.exec_id
            assert t.isin


class TestCcfParser:
    def test_parse_sample(self):
        txns = parse_ccf_file(FIXTURE_DIR / "custodian_statement.ccf")
        assert len(txns) == 99  # ORD20260078 deliberately missing
        assert txns[0].clearing_ref == "ORD20260001"
        assert txns[0].isin == "US5949181045"
        assert txns[0].side == "BUY"
        assert txns[0].quantity == 2500.0
        assert txns[0].price == 418.98
        assert txns[4].side == "SELL"

    def test_exec_id_parsed(self):
        txns = parse_ccf_file(FIXTURE_DIR / "custodian_statement.ccf")
        assert txns[0].exec_id == "EXE10000001"


class TestTradeReconciliation:
    def test_matched_trades(self):
        fix = parse_fix_file(FIXTURE_DIR / "front_office_exec.fix")
        ccf = parse_ccf_file(FIXTURE_DIR / "custodian_statement.ccf")
        cases = reconcile_trades(fix, ccf)
        matched = [c for c in cases if c.exception_flag == "N"]
        assert len(matched) > 0
        for case in matched:
            assert case.match_confidence == 100
            assert case.rule_applied == "T1_EXEC_ID_EXACT"

    def test_quantity_mismatch_detected(self):
        fix = [FixTransaction("ORD-001", "EXE-001", "US1234561098", "BUY", 10_000, 100.0, "", "", "USD", "")]
        ccf = [CcfTransaction("ORD-001", "EXE-001", "US1234561098", "BUY", 9_500, 100.0, "", "")]
        cases = reconcile_trades(fix, ccf)
        assert len(cases) == 1
        assert cases[0].exception_flag == "Y"
        assert cases[0].reason_code == "QUANTITY_MISMATCH"
        assert cases[0].variance == 500.0

    def test_price_break_detected(self):
        fix = [FixTransaction("ORD-001", "EXE-001", "US1234561098", "BUY", 1000, 174.95, "", "", "USD", "")]
        ccf = [CcfTransaction("ORD-001", "EXE-001", "US1234561098", "BUY", 1000, 164.95, "", "")]
        cases = reconcile_trades(fix, ccf)
        assert len(cases) == 1
        assert cases[0].exception_flag == "Y"
        assert cases[0].reason_code == "PRICE_BREAK"
        assert cases[0].rule_applied == "T2_PRICE_BREAK"

    def test_small_price_diff_auto_closes(self):
        fix = [FixTransaction("ORD-001", "EXE-001", "US1234561098", "BUY", 1000, 150.14, "", "", "USD", "")]
        ccf = [CcfTransaction("ORD-001", "EXE-001", "US1234561098", "BUY", 1000, 150.19, "", "")]
        cases = reconcile_trades(fix, ccf)
        assert len(cases) == 1
        assert cases[0].exception_flag == "N"
        assert cases[0].match_confidence == 100

    def test_orphan_trade(self):
        # Different exec_ids on each side -> no match, two orphans.
        fix = [FixTransaction("ORD-001", "EXE-A", "US9999999999", "BUY", 1_000, 1.0, "", "", "USD", "")]
        ccf = [CcfTransaction("ORD-002", "EXE-B", "US1234561098", "BUY", 10_000, 1.0, "", "")]
        cases = reconcile_trades(fix, ccf)
        assert len(cases) == 2
        orphan_fix = next(c for c in cases if c.reason_code == "ORPHAN_FIX")
        orphan_ccf = next(c for c in cases if c.reason_code == "ORPHAN_CCF")
        assert orphan_fix.exception_flag == "Y"
        assert orphan_ccf.exception_flag == "Y"

    def test_case_ids_prefixed_with_t(self):
        fix = parse_fix_file(FIXTURE_DIR / "front_office_exec.fix")
        ccf = parse_ccf_file(FIXTURE_DIR / "custodian_statement.ccf")
        cases = reconcile_trades(fix, ccf)
        for case in cases:
            assert case.case_id.startswith("TCASE-")
