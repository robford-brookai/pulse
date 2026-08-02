"""Tests for ZCC webhook receiver — Zoom HMAC-SHA256 validation, url_validation, event routing."""

from __future__ import annotations

import json

import pytest

from tests.conftest import make_zoom_signature

TIMESTAMP = "1614000000"
SECRET = "test_secret"


def _make_zcc_event(event_type: str = "contact_center.engagement_ended", **overrides) -> dict:
    payload = {
        "event": event_type,
        "payload": {
            "account_id": "abc123",
            "object": {
                "engagement_id": "eng-test-001",
                "assigned_to": {"id": "agent-007"},
                "duration": 180,
                "disposition_name": "resolved",
            },
        },
    }
    payload.update(overrides)
    return payload


def _post_webhook(client, body: bytes, timestamp: str = TIMESTAMP, sig: str | None = None):
    if sig is None:
        sig = make_zoom_signature(body, timestamp, SECRET)
    return client.post(
        "/webhooks/zcc",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-zm-request-timestamp": timestamp,
            "x-zm-signature": sig,
        },
    )


@pytest.mark.asyncio
async def test_valid_signature_accepted(client, mock_publisher):
    """Valid Zoom HMAC-SHA256 signature returns 200."""
    body = json.dumps(_make_zcc_event()).encode()
    resp = await _post_webhook(client, body)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_signature_rejected(client):
    """Mismatched signature returns 401."""
    body = json.dumps(_make_zcc_event()).encode()
    bad_sig = make_zoom_signature(body, TIMESTAMP, "wrong_secret")
    resp = await _post_webhook(client, body, sig=bad_sig)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_url_validation_challenge(client, mock_publisher):
    """endpoint.url_validation returns {plainToken, encryptedToken} without publishing."""
    plain_token = "abc_plain_token_xyz"
    payload = {
        "event": "endpoint.url_validation",
        "payload": {"plainToken": plain_token},
    }
    body = json.dumps(payload).encode()
    resp = await _post_webhook(client, body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plainToken"] == plain_token
    assert "encryptedToken" in data
    mock_publisher.publish.assert_not_called()


@pytest.mark.asyncio
async def test_known_event_normalized_and_published(client, mock_publisher):
    """contact_center.engagement_ended publishes to the interactions domain as call.completed."""
    body = json.dumps(_make_zcc_event("contact_center.engagement_ended")).encode()
    resp = await _post_webhook(client, body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    mock_publisher.publish.assert_called_once()
    call_kwargs = mock_publisher.publish.call_args.kwargs
    assert call_kwargs["detail_type"] == "interactions"

    published = call_kwargs["event"]
    assert published["event_type"] == "call.completed"
    # The key survives the transport change; it groups consumer-side sequence guards.
    assert call_kwargs["key"] == published["entity_id"]


@pytest.mark.asyncio
async def test_unknown_event_logged_and_skipped(client, mock_publisher):
    """Unknown ZCC event returns 200 without publishing (no 4xx, no publish call)."""
    body = json.dumps(_make_zcc_event("contact_center.some_unknown_event")).encode()
    resp = await _post_webhook(client, body)
    assert resp.status_code == 200
    mock_publisher.publish.assert_not_called()
