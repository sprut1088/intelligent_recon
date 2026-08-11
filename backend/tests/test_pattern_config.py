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


def test_pattern_listing_groups_by_name_and_version():
    with TestClient(app) as client:
        client.post(
            "/api/patterns",
            json={
                "pattern_id": "PX-GROUP-1",
                "pattern_name": "P1",
                "pattern_type": "CUSTOM",
                "pattern_group": "Group1",
                "pattern_version": "1.0",
                "pattern_rule": {"fields": ["invoice"]},
                "status": "DRAFT",
                "execution_mode": "SUGGESTION",
                "confidence_threshold": 0.75,
            },
        )
        client.post(
            "/api/patterns",
            json={
                "pattern_id": "PX-GROUP-2",
                "pattern_name": "P2",
                "pattern_type": "CUSTOM",
                "pattern_group": "Group1",
                "pattern_version": "1.0",
                "pattern_rule": {"fields": ["amount"]},
                "status": "DRAFT",
                "execution_mode": "SUGGESTION",
                "confidence_threshold": 0.8,
            },
        )

        response = client.get("/api/patterns")
        assert response.status_code == 200
        body = response.json()
        assert body["grouped_patterns"][0]["group_name"] == "Group1"
        assert [item["pattern_name"] for item in body["grouped_patterns"][0]["items"]] == ["P1", "P2"]
