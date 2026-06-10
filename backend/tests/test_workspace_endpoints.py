from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db


def test_workspace_duco_comparable_endpoints():
    init_db()
    client = TestClient(app)
    client.post('/api/load-sample', json={'reset': True})

    overview = client.get('/api/workspace/overview')
    assert overview.status_code == 200
    data = overview.json()
    assert data['process']['process_id'] == 'IRE-CASH-001'
    assert len(data['capabilities']) >= 5

    predictions = client.get('/api/workspace/match-field-predictions')
    assert predictions.status_code == 200
    assert any(p['left_field'] == 'amount' for p in predictions.json()['predictions'])

    rules = client.get('/api/workspace/no-code-rules')
    assert rules.status_code == 200
    assert len(rules.json()['items']) >= 7

    dashboard = client.get('/api/workspace/dashboard')
    assert dashboard.status_code == 200
    assert 'by_status' in dashboard.json()['charts']

    export = client.get('/api/workspace/export/reconciliation-results')
    assert export.status_code == 200
    assert 'case_id' in export.text
