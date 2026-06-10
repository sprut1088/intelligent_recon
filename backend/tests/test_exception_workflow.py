from fastapi.testclient import TestClient

from app.main import app


def test_exception_workflow_supports_assignment_and_status_update():
    with TestClient(app) as client:
        client.post("/api/load-sample", json={"reset": True})
        queue = client.get("/api/exceptions/workflow?limit=5")
        assert queue.status_code == 200
        payload = queue.json()
        assert payload["items"]
        case_id = payload["items"][0]["case_id"]

        update = client.patch(
            f"/api/exceptions/{case_id}/workflow",
            json={
                "owner": "analyst_01",
                "priority": "High",
                "workflow_status": "IN_REVIEW",
                "comment": "Assigned during pytest workflow validation",
                "updated_by": "pytest",
            },
        )
        assert update.status_code == 200
        body = update.json()
        assert body["owner"] == "analyst_01"
        assert body["priority"] == "High"
        assert body["workflow_status"] == "IN_REVIEW"
        assert body["comments"]
