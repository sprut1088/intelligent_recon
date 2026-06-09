from app.parsers import parse_psr_file, parse_camt_file
from app.config import settings
from app.loader import load_samples_and_reconcile
from app.db import get_conn, init_db

def test_sample_parsers_load_records():
    header, psr = parse_psr_file(settings.psr_sample_path)
    camt = parse_camt_file(settings.camt_sample_path)
    assert header is not None
    assert len(psr) >= 10000
    assert len(camt) > 0
    assert psr[0].id == "TX-2026-0001"

def test_reconciliation_creates_cases():
    init_db()
    result = load_samples_and_reconcile(reset=True)
    assert result["case_count"] > 0
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM recon_cases").fetchone()["cnt"]
    assert total == result["case_count"]
