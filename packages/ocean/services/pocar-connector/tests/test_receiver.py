"""Tests for POCAR webhook receiver — signature validation and routing."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest


def _make_payload() -> dict:
    return {
        "alert_id": "alert-test-001",
        "patient_id": "pt-abc123",
        "alert_type": "glucose_missing",
        "severity": "urgent",
        "clinic_id": "clinic-1",
        "triggered_at": "2026-03-05T10:00:00Z",
    }


def _sign(payload_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    """GET /health returns 200 with status=ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "pocar-connector"


@pytest.mark.asyncio
async def test_valid_signature_accepted(client):
    """POST /webhooks/pocar with valid HMAC-SHA256 returns 200 with status=accepted."""
    payload = _make_payload()
    body = json.dumps(payload).encode()
    sig = _sign(body, "test_secret")
    resp = await client.post(
        "/webhooks/pocar",
        content=body,
        headers={"Content-Type": "application/json", "X-Pocar-Signature": sig},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert "event_id" in data


@pytest.mark.asyncio
async def test_invalid_signature_rejected(client):
    """POST /webhooks/pocar with wrong signature returns 401."""
    payload = _make_payload()
    body = json.dumps(payload).encode()
    sig = _sign(body, "wrong_secret")
    resp = await client.post(
        "/webhooks/pocar",
        content=body,
        headers={"Content-Type": "application/json", "X-Pocar-Signature": sig},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_signature_rejected(client):
    """POST /webhooks/pocar with no X-Pocar-Signature header returns 401."""
    payload = _make_payload()
    body = json.dumps(payload).encode()
    resp = await client.post(
        "/webhooks/pocar",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401
