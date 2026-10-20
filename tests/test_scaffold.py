"""CPU-only checks for the installed API boundary and package wiring."""

from fastapi.testclient import TestClient

import inferlab_core
from inferlab_api.main import app


def test_local_health_does_not_claim_gpu_readiness() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "execution": "not_configured"}


def test_no_experiment_submission_is_exposed() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/experiments", json={}).status_code == 404
        assert client.get("/health", headers={"host": "untrusted.example"}).status_code == 400


def test_core_is_installed_as_a_package() -> None:
    assert inferlab_core.__name__ == "inferlab_core"
