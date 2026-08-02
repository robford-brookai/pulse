"""Tests for the Impilo webhook receiver endpoint."""
from __future__ import annotations

import inspect
import json

import pytest


VALID_READING_BODY = json.dumps({
    "type": "reading.weight",
    "id": 456,
    "patient": {"id": 123},
    "value": 185.5,
    "unit": "lbs",
    "createdAt": "2026-03-06T10:00:00Z",
})


@pytest.mark.anyio
async def test_health_returns_ok(client) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "impilo-connector"


@pytest.mark.anyio
async def test_valid_api_key_accepted(client) -> None:
    resp = await client.post(
        "/webhooks/impilo",
        content=VALID_READING_BODY,
        headers={
            "Impilo-API-Key": "test_impilo_key",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert "event_id" in data


@pytest.mark.anyio
async def test_invalid_api_key_rejected(client) -> None:
    resp = await client.post(
        "/webhooks/impilo",
        content=VALID_READING_BODY,
        headers={
            "Impilo-API-Key": "wrong_key",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_missing_api_key_rejected(client) -> None:
    resp = await client.post(
        "/webhooks/impilo",
        content=VALID_READING_BODY,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_api_key_uses_timing_safe_comparison() -> None:
    from src.receiver import _validate_api_key

    source = inspect.getsource(_validate_api_key)
    assert "compare_digest" in source
