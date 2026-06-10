from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def _upload_sample_batch(client: TestClient) -> str:
    root = Path(__file__).resolve().parents[1] / "sample_data"
    with (root / "psr_10000_payments.txt").open("rb") as psr_handle:
        psr_resp = client.post(
            "/api/files/upload",
            data={"file_type": "PSR", "batch_name": "pytest data quality batch"},
            files={"file": ("psr.txt", psr_handle, "text/plain")},
        )
    batch_id = psr_resp.json()["batch"]["batch_id"]
    with (root / "camt_10000_payments.xml").open("rb") as camt_handle:
        client.post(
            "/api/files/upload",
            data={"file_type": "CAMT", "batch_id": batch_id},
            files={"file": ("camt.xml", camt_handle, "application/xml")},
        )
    return batch_id


def test_data_quality_report_profiles_uploaded_batch():
    with TestClient(app) as client:
        batch_id = _upload_sample_batch(client)
        response = client.post(f"/api/data-quality/batches/{batch_id}/validate")
        assert response.status_code == 200
        payload = response.json()
        assert payload["batch_id"] == batch_id
        assert len(payload["files"]) == 2
        assert payload["warning_count"] >= 0
        assert payload["error_count"] == 0
        assert any(issue["issue_code"] == "PSR_TRAILER_MISSING" for issue in payload["issues"])
