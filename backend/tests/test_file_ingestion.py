from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app



def test_sample_files_can_be_uploaded_and_run_as_batch():
    root = Path(__file__).resolve().parents[1] / "sample_data"
    with TestClient(app) as client:
        with (root / "psr_10000_payments.txt").open("rb") as psr_handle:
            psr_resp = client.post(
            "/api/files/upload",
            data={"file_type": "PSR", "batch_name": "pytest upload batch"},
            files={"file": ("psr.txt", psr_handle, "text/plain")},
        )
        assert psr_resp.status_code == 200
        batch_id = psr_resp.json()["batch"]["batch_id"]

        with (root / "camt_10000_payments.xml").open("rb") as camt_handle:
            camt_resp = client.post(
            "/api/files/upload",
            data={"file_type": "CAMT", "batch_id": batch_id},
            files={"file": ("camt.xml", camt_handle, "application/xml")},
        )
        assert camt_resp.status_code == 200

        detail = client.get(f"/api/files/batches/{batch_id}")
        assert detail.status_code == 200
        assert len(detail.json()["files"]) == 2

        run_resp = client.post(f"/api/files/batches/{batch_id}/run", json={"reset": True})
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["psr_count"] > 0
        assert payload["camt_count"] > 0
        assert payload["case_count"] > 0
