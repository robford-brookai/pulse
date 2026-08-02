"""Test fixtures for zcc-connector — mock publisher and Zoom HMAC helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock


def make_zoom_signature(body: bytes, timestamp: str, secret: str) -> str:
    """Compute Zoom v0 HMAC-SHA256 signature."""
    message = f"v0:{timestamp}:{body.decode('utf-8')}"
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"v0={sig}"


@pytest.fixture
def mock_publisher():
    """AsyncMock publisher that records publish() calls without touching Redpanda."""
    pub = AsyncMock()
    pub.publish = AsyncMock(return_value=None)
    return pub


@pytest_asyncio.fixture
async def client(mock_publisher, monkeypatch):
    """AsyncClient with lifespan bypassed — publisher injected directly."""
    monkeypatch.setenv("ZCC_WEBHOOK_SECRET", "test_secret")
    from src.main import app
    app.state.publisher = mock_publisher
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
