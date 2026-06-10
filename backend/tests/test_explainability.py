from fastapi.testclient import TestClient

from app.main import app


def test_case_explanation_contains_score_breakdown():
    with TestClient(app) as client:
        client.post("/api/load-sample", json={"reset": True})
        cases = client.get("/api/reconcile/cases?limit=1").json()["items"]
        assert cases
        case_id = cases[0]["case_id"]
        response = client.get(f"/api/reconcile/cases/{case_id}/explanation")
        assert response.status_code == 200
        payload = response.json()
        assert payload["score_breakdown"]["engine_confidence"] >= 0
        assert payload["score_breakdown"]["components"]
        assert "decision_basis" in payload["score_breakdown"]
