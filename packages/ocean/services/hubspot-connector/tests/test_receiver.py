"""Tests for HubSpot webhook receiver — signature verification, event routing."""

from __future__ import annotations

import hashlib
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

CLIENT_SECRET = "test-hubspot-secret"


@pytest.fixture()
def _set_env(monkeypatch):
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")


def _sign(method: str, url: str, body: bytes, timestamp: str) -> str:
    """Compute HubSpot v3 signature: SHA256(secret + method + url + body + timestamp)."""
    source = CLIENT_SECRET + method + url + body.decode("utf-8") + timestamp
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _make_contact_event(*, sub_type: str = "contact.creation", object_id: int = 12345) -> dict:
    return {
        "subscriptionType": sub_type,
        "objectId": object_id,
        "changeSource": "CRM",
    }


def _make_property_change_event(*, prop_name: str = "lifecyclestage", prop_value: str = "customer") -> dict:
    return {
        "subscriptionType": "contact.propertyChange",
        "objectId": 12345,
        "changeSource": "CRM",
        "propertyName": prop_name,
        "propertyValue": prop_value,
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
        body = json.dumps([_make_contact_event()]).encode()
        ts = str(int(time.time()))
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": "bad-signature",
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_valid_signature_returns_200(self, client):
        test_client, _ = client
        body = json.dumps([_make_contact_event()]).encode()
        ts = str(int(time.time()))
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200

    def test_expired_timestamp_returns_401(self, client):
        test_client, _ = client
        body = json.dumps([_make_contact_event()]).encode()
        old_ts = str(int(time.time()) - 600)
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, old_ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": old_ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 401


class TestContactEvents:
    def test_contact_creation_publishes(self, client):
        test_client, mock_pub = client
        body = json.dumps([_make_contact_event(sub_type="contact.creation")]).encode()
        ts = str(int(time.time()))
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        mock_pub.publish.assert_called_once()

    def test_contact_deletion_publishes(self, client):
        test_client, mock_pub = client
        body = json.dumps([_make_contact_event(sub_type="contact.deletion")]).encode()
        ts = str(int(time.time()))
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_unsupported_subscription_skipped(self, client):
        test_client, mock_pub = client
        body = json.dumps([{"subscriptionType": "deal.creation", "objectId": 999}]).encode()
        ts = str(int(time.time()))
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        mock_pub.publish.assert_not_called()


class TestPHISafety:
    def test_phi_field_redacted(self, client):
        test_client, mock_pub = client
        body = json.dumps([_make_property_change_event(prop_name="email", prop_value="patient@example.com")]).encode()
        ts = str(int(time.time()))
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        event = mock_pub.publish.call_args.kwargs["event"]
        assert event["payload"]["property_value"] == "[REDACTED]"

    def test_safe_field_passes_through(self, client):
        test_client, mock_pub = client
        body = json.dumps([_make_property_change_event(prop_name="lifecyclestage", prop_value="customer")]).encode()
        ts = str(int(time.time()))
        url = "http://testserver/webhook"
        sig = _sign("POST", url, body, ts)
        resp = test_client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        event = mock_pub.publish.call_args.kwargs["event"]
        assert event["payload"]["property_value"] == "customer"


class TestHealthEndpoint:
    def test_health_returns_200(self, _set_env):
        from src.main import app

        test_client = TestClient(app)
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "hubspot-connector"
