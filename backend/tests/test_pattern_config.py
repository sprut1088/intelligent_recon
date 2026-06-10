from fastapi.testclient import TestClient

from app.main import app


def test_pattern_registry_can_create_update_and_toggle_pattern():
    with TestClient(app) as client:
        create_resp = client.post(
            "/api/patterns",
            json={
                "pattern_id": "PX-TEST",
                "pattern_name": "Test Configurable Pattern",
                "pattern_type": "CUSTOM",
                "pattern_rule": {"fields": ["invoice", "amount"], "threshold": 0.88},
                "status": "DRAFT",
                "execution_mode": "SUGGESTION",
                "confidence_threshold": 0.88,
            },
        )
        assert create_resp.status_code == 200
        assert create_resp.json()["pattern_rule"]["threshold"] == 0.88

        patch_resp = client.patch("/api/patterns/PX-TEST", json={"status": "ACTIVE", "confidence_threshold": 0.91})
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "ACTIVE"
        assert patch_resp.json()["confidence_threshold"] == 0.91

        off_resp = client.post("/api/patterns/PX-TEST/deactivate")
        assert off_resp.status_code == 200
        assert off_resp.json()["status"] == "INACTIVE"

        on_resp = client.post("/api/patterns/PX-TEST/activate")
        assert on_resp.status_code == 200
        assert on_resp.json()["status"] == "ACTIVE"
