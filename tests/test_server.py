"""API smoke tests (spec §19). Skipped when FastAPI / the warehouse are absent."""
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
import llmmeta.server as srv

pytestmark = pytest.mark.skipif(
    srv.app is None or not Path(srv.DB_PATH).exists(),
    reason="FastAPI not installed or warehouse not built (run `make all`)",
)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(srv.app)


def test_read_endpoints(client):
    assert client.get("/sources").status_code == 200
    assert len(client.get("/sources").json()) > 0
    assert client.get("/benchmarks").status_code == 200
    assert client.get("/prices").status_code == 200
    assert "finance_deep_research_under_3" in client.get("/profiles").json()


def test_recommend_endpoint(client):
    # no as_of → server uses the latest snapshot date present (robust to rebuild date)
    r = client.post("/recommend", json={"profile": "finance_deep_research_under_3"})
    assert r.status_code == 200
    body = r.json()
    assert body["recommended_default"] is not None
    assert "coverage" in body["recommended_default"]


def test_route_endpoint(client):
    r = client.post("/route", json={"profile": "coding_agent_balanced", "risk_tier": "low"})
    assert r.status_code == 200
    assert r.json()["decision"] is not None


def test_unknown_profile_404(client):
    assert client.post("/recommend", json={"profile": "nope"}).status_code == 404
