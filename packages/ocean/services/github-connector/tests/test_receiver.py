"""Tests for GitHub webhook receiver — signature verification, event routing."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

WEBHOOK_SECRET = "test-github-secret"


@pytest.fixture()
def _set_env(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")


def _sign(body: bytes) -> str:
    """Compute GitHub-style sha256=<hex> signature."""
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _make_pr_payload(*, action: str = "opened", merged: bool = False) -> dict:
    pr = {
        "number": 42,
        "title": "Add feature X",
        "merged": merged,
        "user": {"login": "dev1"},
        "base": {"ref": "main"},
        "head": {"ref": "feature-x"},
    }
    return {
        "action": action,
        "pull_request": pr,
        "repository": {"full_name": "brookai/ocean"},
        "sender": {"login": "dev1"},
    }


def _make_push_payload() -> dict:
    return {
        "ref": "refs/heads/main",
        "after": "abc123def456789",
        "commits": [{"id": "abc123def456789", "message": "fix: something"}],
        "repository": {"full_name": "brookai/ocean"},
        "sender": {"login": "dev1"},
        "pusher": {"name": "dev1"},
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
        body = json.dumps(_make_pr_payload()).encode()
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": "sha256=bad",
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_valid_signature_returns_200(self, client):
        test_client, _ = client
        body = json.dumps(_make_pr_payload()).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200


class TestPullRequestEvents:
    def test_pr_opened_publishes(self, client):
        test_client, mock_pub = client
        body = json.dumps(_make_pr_payload(action="opened")).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        mock_pub.publish.assert_called_once()
        call_args = mock_pub.publish.call_args
        assert call_args.kwargs["topic"] == "ocean.signals" or call_args[1].get("topic") == "ocean.signals"

    def test_pr_merged_publishes(self, client):
        test_client, mock_pub = client
        body = json.dumps(_make_pr_payload(action="closed", merged=True)).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        published_value = mock_pub.publish.call_args[1].get("value") or mock_pub.publish.call_args[0][2]
        event = json.loads(published_value)
        assert event["event_type"] == "pr.merged"

    def test_pr_closed_without_merge(self, client):
        test_client, mock_pub = client
        body = json.dumps(_make_pr_payload(action="closed", merged=False)).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        published_value = mock_pub.publish.call_args[1].get("value") or mock_pub.publish.call_args[0][2]
        event = json.loads(published_value)
        assert event["event_type"] == "pr.closed"

    def test_unsupported_pr_action_skipped(self, client):
        test_client, mock_pub = client
        body = json.dumps(_make_pr_payload(action="labeled")).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "pull_request",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        mock_pub.publish.assert_not_called()


class TestPushEvents:
    def test_push_publishes(self, client):
        test_client, mock_pub = client
        body = json.dumps(_make_push_payload()).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "push",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        published_value = mock_pub.publish.call_args[1].get("value") or mock_pub.publish.call_args[0][2]
        event = json.loads(published_value)
        assert event["event_type"] == "commit.pushed"
        assert event["entity_id"] == "brookai/ocean@abc123def456"


class TestUnsupportedEvents:
    def test_unknown_event_skipped(self, client):
        test_client, mock_pub = client
        body = json.dumps({"action": "created"}).encode()
        sig = _sign(body)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": "issues",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        mock_pub.publish.assert_not_called()


class TestHealthEndpoint:
    def test_health_returns_200(self, _set_env):
        from src.main import app

        test_client = TestClient(app)
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "github-connector"
