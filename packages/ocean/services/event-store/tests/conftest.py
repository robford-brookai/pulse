"""Test fixtures for event-store — mock consumer and AsyncClient."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


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
async def client(monkeypatch):
    monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

    async def _noop_consumer(*args, **kwargs):
        await asyncio.sleep(9999)

    with patch("src.consumer.run_consumer", side_effect=_noop_consumer):
        from src.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
