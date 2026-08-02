"""Tests for event-store /health endpoint."""

from __future__ import annotations


async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "event-store"


async def test_health_version(client):
    response = await client.get("/health")
    assert response.json()["version"] == "0.1.0"
