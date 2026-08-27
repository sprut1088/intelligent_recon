"""Agent-driven end-to-end trade AI Pass test. Delete after demo."""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8090"
FIX = Path(r"c:\git_repos\intelligent_recon\front_office_exec.fix")
CCF = Path(r"c:\git_repos\intelligent_recon\custodian_statement_fuzzy_matching.ccf")
DB = Path(r"c:\git_repos\intelligent_recon\backend\runtime_data\recon.db")


def upload(client: httpx.Client, path: Path, file_type: str, batch_id: str | None) -> dict:
    data = {"file_type": file_type, "created_by": "agent_test"}
    if batch_id:
        data["batch_id"] = batch_id
    else:
        data["batch_name"] = "ai-fuzzy-typo-test"
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, "application/octet-stream")}
        r = client.post(f"{BASE}/api/files/upload", data=data, files=files, timeout=60.0)
    r.raise_for_status()
    return r.json()


def main() -> int:
    with httpx.Client() as c:
        print("=== Uploading FIX ===")
        fix_resp = upload(c, FIX, "FIX", None)
        batch_id = fix_resp["batch"]["batch_id"]
        print(f"batch_id = {batch_id}")

        print("=== Uploading CCF ===")
        upload(c, CCF, "CCF", batch_id)

        print("=== Running deterministic trade recon ===")
        r = c.post(f"{BASE}/api/files/batches/{batch_id}/run-trade", timeout=120.0)
        r.raise_for_status()
        print(json.dumps(r.json(), indent=2))

        print("=== Running AI Pass ===")
        r = c.post(f"{BASE}/api/reconcile/ai-pass", timeout=300.0)
        r.raise_for_status()
        print(json.dumps(r.json(), indent=2))

    print()
    print("=== DB inspection ===")
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Count cases by status.
    print("-- Cases by reconciliation_status --")
    for row in conn.execute(
        "SELECT reconciliation_status, COUNT(*) AS n FROM recon_cases GROUP BY reconciliation_status ORDER BY n DESC"
    ):
        print(f"  {row['reconciliation_status']}: {row['n']}")

    print()
    print("-- Cases involving EXE10000095 / EXE1000095 --")
    q = """
    SELECT case_id, reconciliation_status, rule_applied, match_confidence,
           psr_id, camt_id, reference, counterparty, explanation
    FROM recon_cases
    WHERE psr_id LIKE '%EXE10000095%'
       OR camt_id LIKE '%EXE1000095%'
       OR psr_id LIKE '%EXE1000095%'
       OR camt_id LIKE '%EXE10000095%'
       OR reference LIKE '%ORD20260095%'
       OR reference LIKE '%ORD20260-95%'
    ORDER BY case_id
    """
    hits = list(conn.execute(q))
    if not hits:
        print("  (no matching rows)")
    for row in hits:
        print(f"  case_id={row['case_id']}")
        print(f"    status={row['reconciliation_status']} rule={row['rule_applied']} conf={row['match_confidence']}")
        print(f"    psr_id={row['psr_id']} camt_id={row['camt_id']}")
        print(f"    reference={row['reference']} counterparty={row['counterparty']}")
        print(f"    explanation={row['explanation'][:400] if row['explanation'] else ''}")
        print()

    print("-- AI-generated cases (case_id starts with AI-) --")
    ai_rows = list(conn.execute(
        "SELECT case_id, reconciliation_status, rule_applied, match_confidence, psr_id, camt_id "
        "FROM recon_cases WHERE case_id LIKE 'AI-%' ORDER BY case_id LIMIT 20"
    ))
    for row in ai_rows:
        print(f"  {row['case_id']} status={row['reconciliation_status']} rule={row['rule_applied']} conf={row['match_confidence']} psr={row['psr_id']} ccf={row['camt_id']}")
    if not ai_rows:
        print("  (none)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
