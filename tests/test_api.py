from fastapi.testclient import TestClient

from incidentlens.api import app


def test_api_lifecycle_stale_state_and_local_boundary(lab):
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/state").json()["experiment_id"] is None
        first = client.post("/api/lab/baseline").json()["experiment_id"]
        payload = {"experiment_id": first}
        assert client.post("/api/lab/recover", json=payload).status_code == 409
        assert client.post("/api/lab/incident", json=payload).status_code == 200
        report = client.post("/api/investigate", json=payload)
        assert report.status_code == 200, report.text
        assert len(report.json()["trace"]) == 5
        assert client.post("/api/lab/recover", json=payload).status_code == 200
        assert 'phase="recovery"' in client.get("/metrics").text
        assert client.post("/api/lab/baseline").status_code == 200
        assert client.post("/api/investigate", json=payload).status_code == 409
        assert (
            client.post("/api/lab/baseline", headers={"Origin": "https://evil.test"}).status_code
            == 403
        )
        assert client.get("/api/state", headers={"Host": "evil.test"}).status_code == 403


def test_busy_operation_is_rejected(lab):
    with TestClient(app) as client:
        # The lock itself is tested rather than relying on scheduling races in CI.
        class Busy:
            def locked(self):
                return True

        app.state.gate = Busy()
        assert client.post("/api/lab/baseline").status_code == 409
