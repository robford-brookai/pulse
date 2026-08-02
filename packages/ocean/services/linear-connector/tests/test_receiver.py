"""Tests for Linear webhook receiver — signature verification, ocean label filter."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

WEBHOOK_SECRET = "test-linear-secret"


@pytest.fixture()
def _set_env(monkeypatch):
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")


def _sign(body: bytes) -> str:
    """Compute Linear-style HMAC-SHA256 signature."""
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _make_issue_payload(*, labels: list[dict] | None = None, action: str = "create") -> dict:
    return {
        "action": action,
        "type": "Issue",
        "data": {
            "id": "issue-1",
            "title": "Test issue from Linear",
            "priority": 2,
            "url": "https://linear.app/brook/issue/BROOK-1",
            "labels": labels or [],
        },
    }


@pytest.fixture()
def client(_set_env):
    """TestClient with mocked publisher."""
    from src.main import app

    mock_pub = AsyncMock()
    app.state.publisher = mock_pub
    return TestClient(app, raise_server_exceptions=False), mock_pub


class TestWebhookSignature:
    def test_invalid_signature_returns_401(self, client):
        test_client, _ = client
        body = json.dumps(_make_issue_payload()).encode()
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={"linear-signature": "bad-signature", "content-type": "application/json"},
        )
        assert resp.status_code == 401

    def test_valid_signature_returns_200(self, client):
        test_client, _ = client
        payload = _make_issue_payload(labels=[{"name": "ocean"}])
        body = json.dumps(payload).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={"linear-signature": sig, "content-type": "application/json"},
        )
        assert resp.status_code == 200


class TestOceanLabelFilter:
    def test_valid_webhook_with_ocean_label_publishes(self, client):
        test_client, mock_pub = client
        payload = _make_issue_payload(labels=[{"name": "ocean"}, {"name": "device"}])
        body = json.dumps(payload).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={"linear-signature": sig, "content-type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        mock_pub.publish.assert_called_once()

    def test_valid_webhook_without_ocean_label_skips(self, client):
        test_client, mock_pub = client
        payload = _make_issue_payload(labels=[{"name": "some-other-label"}])
        body = json.dumps(payload).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={"linear-signature": sig, "content-type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        mock_pub.publish.assert_not_called()


class TestHealthEndpoint:
    def test_health_returns_200(self, _set_env):
        from src.main import app

        test_client = TestClient(app)
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "linear-connector"
