from app.db import get_conn, init_db
from app.learning import approve_candidate, run_learning, seed_demo_learning_signals
from app.loader import load_samples_and_reconcile, rerun_reconciliation_only


def test_sample_reconciliation_and_learning_flow():
    init_db()
    stats = load_samples_and_reconcile(reset=True)
    assert stats["psr_count"] == 10000
    assert stats["camt_count"] > 0
    assert stats["case_count"] >= 10000

    rerun = rerun_reconciliation_only()
    assert rerun["case_count"] >= 10000

    demo = seed_demo_learning_signals()
    assert demo["inserted_demo_signals"] >= 3

    learning = run_learning()
    assert len(learning["candidates"]) >= 1
    candidate = learning["candidates"][0]
    approved = approve_candidate(candidate["candidate_pattern_id"], "pytest", "SUGGESTION", 0.90)
    assert approved["status"] == "APPROVED"

    with get_conn() as conn:
        active = conn.execute("SELECT COUNT(*) AS cnt FROM recon_pattern_registry WHERE pattern_type='LEARNED' AND status='ACTIVE'").fetchone()["cnt"]
    assert active >= 1
