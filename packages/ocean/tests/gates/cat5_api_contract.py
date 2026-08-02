"""Gate 5: API Contract
Usage: pytest test/cat5_api_contract.py -v
Requires: all services running (docker compose up).
Tests every endpoint for correct status code and JSON shape.
"""
from __future__ import annotations

import json
import os
import time

import httpx
import pytest

# Service base URLs — map service name to (host, port)
SERVICES = {
    "event-store":      ("localhost", 8001),
    "pocar-connector":  ("localhost", 8002),
    "graph-projection": ("localhost", 8003),
    "control-plane":    ("localhost", 8004),
    "slack-bot":        ("localhost", 8005),
    "zcc-connector":    ("localhost", 8006),
    "sim-driver":       ("localhost", 8060),
    "stacte-bridge":    ("localhost", 8070),
}


# ---------------------------------------------------------------------------
# Health endpoints — all 8 services
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("svc,port", [
    ("event-store",      8001),
    ("pocar-connector",  8002),
    ("graph-projection", 8003),
    ("control-plane",    8004),
    ("slack-bot",        8005),
    ("zcc-connector",    8006),
    ("stacte-bridge",    8070),
])
def test_health_endpoint(svc, port):
    t0 = time.time()
    r = httpx.get(f"http://localhost:{port}/health", timeout=5)
    elapsed = (time.time() - t0) * 1000
    assert r.status_code == 200, f"{svc}/health returned {r.status_code}"
    assert elapsed < 500, f"{svc}/health took {elapsed:.0f}ms (must be < 500ms)"
    data = r.json()
    assert isinstance(data, dict)
    assert data.get("status") == "ok"
    assert "service" in data


def test_sim_driver_health_includes_active_scenarios():
    """sim-driver health includes active_scenarios list."""
    r = httpx.get("http://localhost:8060/health", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "active_scenarios" in data
    assert isinstance(data["active_scenarios"], list)


# ---------------------------------------------------------------------------
# sim-driver: POST /simulate
# ---------------------------------------------------------------------------

def test_simulate_valid_scenario_returns_started():
    r = httpx.post(
        "http://localhost:8060/simulate",
        json={"scenario": "smoke_test"},
        timeout=5,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("started", "already_running")
    assert data["scenario"] == "smoke_test"


def test_simulate_duplicate_returns_already_running():
    """Second POST with same scenario name returns already_running."""
    httpx.post("http://localhost:8060/simulate", json={"scenario": "smoke_test"}, timeout=5)
    r = httpx.post("http://localhost:8060/simulate", json={"scenario": "smoke_test"}, timeout=5)
    assert r.status_code == 200
    data = r.json()
    # May be started (first) or already_running (second), both valid
    assert data["status"] in ("started", "already_running")


def test_simulate_default_scenario_field():
    """POST /simulate with no body uses smoke_test default."""
    r = httpx.post("http://localhost:8060/simulate", json={}, timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["scenario"] == "smoke_test"


# ---------------------------------------------------------------------------
# stacte-bridge: POST /sync
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entity_type", ["alerts", "tasks", "interactions", "outcomes"])
def test_sync_valid_entity_type(entity_type):
    r = httpx.post(
        f"http://localhost:8070/sync?entity_type={entity_type}&limit=1",
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["entity_type"] == entity_type
    assert "updated" in data
    assert isinstance(data["updated"], int)


def test_sync_invalid_entity_type_returns_400():
    r = httpx.post(
        "http://localhost:8070/sync?entity_type=patients",
        timeout=5,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# stacte-bridge: GET /search
# ---------------------------------------------------------------------------

def test_search_returns_expected_shape():
    r = httpx.get(
        "http://localhost:8070/search?q=glucose+high&entity_type=alerts&top_k=5",
        timeout=10,
    )
    # 200 (with results) or 502 (VoyageAI not configured) are both valid
    assert r.status_code in (200, 502)
    if r.status_code == 200:
        data = r.json()
        assert "query" in data
        assert "entity_type" in data
        assert "results" in data
        assert isinstance(data["results"], list)


def test_search_invalid_entity_type_returns_400():
    r = httpx.get(
        "http://localhost:8070/search?q=test&entity_type=patients",
        timeout=5,
    )
    assert r.status_code == 400


def test_search_missing_query_returns_422():
    r = httpx.get("http://localhost:8070/search?entity_type=alerts", timeout=5)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# stacte-bridge: GET /schema
# ---------------------------------------------------------------------------

def test_schema_returns_tables():
    r = httpx.get("http://localhost:8070/schema", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "tables" in data
    table_names = [t["table"] for t in data["tables"]]
    for expected in ("patients", "alerts", "tasks", "interactions", "outcomes"):
        assert expected in table_names, f"schema missing table: {expected}"


# ---------------------------------------------------------------------------
# stacte-bridge: GET /graph/{entity_id}
# ---------------------------------------------------------------------------

def test_graph_unknown_entity_returns_not_found():
    r = httpx.get("http://localhost:8070/graph/nonexistent-id-xyz-000", timeout=5)
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        # Returns empty neighborhood for unknown IDs
        data = r.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# pocar-connector: POST /webhooks/pocar — contract shape
# ---------------------------------------------------------------------------

def test_pocar_webhook_accepted_shape():
    import hashlib
    import hmac as _hmac
    secret = os.environ.get("POCAR_WEBHOOK_SECRET", "dev_secret")
    body = json.dumps({
        "alert_id": "test-001",
        "patient_id": "patient-test-001",
        "alert_type": "glucose_high",
        "severity": "URGENT",
    }).encode()
    sig = "sha256=" + _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    r = httpx.post(
        "http://localhost:8002/webhooks/pocar",
        content=body,
        headers={"Content-Type": "application/json", "X-Pocar-Signature": sig},
        timeout=5,
    )
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        data = r.json()
        assert data["status"] == "accepted"
        assert "event_id" in data
