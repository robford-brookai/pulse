"""Test fixtures for pocar-connector — mock publisher and session maker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_publisher():
    """AsyncMock publisher that records publish() calls without touching the bus."""
    pub = AsyncMock()
    pub.publish = AsyncMock(return_value=None)
    return pub


@pytest.fixture
def mock_session_maker():
    """Mock session maker that returns a no-op async context manager."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    session.begin = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    maker = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return maker


@pytest_asyncio.fixture
async def client(mock_publisher, mock_session_maker, monkeypatch):
    """AsyncClient with lifespan bypassed — publisher and session_maker injected directly."""
    monkeypatch.setenv("POCAR_WEBHOOK_SECRET", "test_secret")
    from src.main import app

    # Inject mocks before any request — bypasses real lifespan startup
    app.state.publisher = mock_publisher
    app.state.session_maker = mock_session_maker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
