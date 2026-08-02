"""Shared fixtures for impilo-connector tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_publisher():
    pub = AsyncMock()
    pub.publish = AsyncMock(return_value=None)
    return pub


@pytest.fixture
def mock_session_maker():
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
    monkeypatch.setenv("IMPILO_API_KEY", "test_impilo_key")
    from src.main import app

    app.state.publisher = mock_publisher
    app.state.session_maker = mock_session_maker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
