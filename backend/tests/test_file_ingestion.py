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


def test_run_batch_with_pattern_version_selection():
    root = Path(__file__).resolve().parents[1] / "sample_data"
    with TestClient(app) as client:
        # upload sample PSR and CAMT files for a new batch
        with (root / "psr_10000_payments.txt").open("rb") as psr_handle:
            psr_resp = client.post(
                "/api/files/upload",
                data={"file_type": "PSR", "batch_name": "pytest upload batch version"},
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

        # create a test pattern version that should still be accepted by the run endpoint
        pattern_resp = client.post(
            "/api/patterns",
            json={
                "pattern_name": "versioned-run-test",
                "pattern_type": "CUSTOM",
                "pattern_version": "2.0",
                "pattern_rule": {"fields": ["reference"], "regex": "\\\d+"},
                "status": "ACTIVE",
                "execution_mode": "SUGGESTION",
                "confidence_threshold": 0.85,
                "approved_by": "pytest",
            },
        )
        assert pattern_resp.status_code == 200
        assert pattern_resp.json()["pattern_version"] == "2.0"

        run_resp = client.post(
            f"/api/files/batches/{batch_id}/run",
            json={"reset": True, "pattern_version": "2.0"},
        )
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["psr_count"] > 0
        assert payload["camt_count"] > 0
        assert payload["case_count"] > 0


def test_auto_pattern_recognition_with_camt_and_psr_files():
    root = Path(__file__).resolve().parents[1] / "sample_data"
    with TestClient(app) as client:
        with (root / "camt_10000_payments.xml").open("rb") as camt_handle:
            with (root / "psr_10000_payments.txt").open("rb") as psr_handle:
                resp = client.post(
                    "/api/files/recognize-patterns",
                    files={
                        "camt_file": ("camt.xml", camt_handle, "application/xml"),
                        "other_file": ("psr.txt", psr_handle, "text/plain"),
                    },
                )

        assert resp.status_code == 200
        result = resp.json()
        assert result["recognized_type"] == "PSR"
        assert result["camt"]["transaction_count"] > 0
        assert result["other"]["psr_transaction_count"] > 0


def test_generate_reconciliation_patterns_from_camt_and_psr_files():
    root = Path(__file__).resolve().parents[1] / "sample_data"
    with TestClient(app) as client:
        with (root / "camt_10000_payments.xml").open("rb") as camt_handle:
            with (root / "psr_10000_payments.txt").open("rb") as psr_handle:
                resp = client.post(
                    "/api/files/reconcile-patterns",
                    files={
                        "camt_file": ("camt.xml", camt_handle, "application/xml"),
                        "other_file": ("psr.txt", psr_handle, "text/plain"),
                    },
                )

        assert resp.status_code == 200
        result = resp.json()
        assert isinstance(result, dict)
        assert result.get("mapping_key") in {"id", "reference", "invoice"}
        assert result.get("pattern_rule") is not None
        assert result["pattern_rule"].get("fields")
        assert result.get("regex_inferred") is not None
