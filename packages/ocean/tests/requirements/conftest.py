"""Shared fixtures for requirement traceability tests.

Provides lightweight mock publisher and session-maker so individual test
files do not need to repeat this setup boilerplate.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_publisher():
    """AsyncMock publisher that records publish(topic, payload) calls."""
    pub = AsyncMock()
    pub.publish = AsyncMock(return_value=None)
    return pub


@pytest.fixture
def mock_session():
    """Mock async SQLAlchemy session with execute + commit recorders."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_session_maker(mock_session):
    """MagicMock session-maker returning mock_session from context manager."""
    maker = MagicMock(return_value=mock_session)
    return maker
