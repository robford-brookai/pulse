"""Shared fixtures for requirement traceability tests.

Provides lightweight mock publisher and session-maker so individual test
files do not need to repeat this setup boilerplate.

Also provides real Postgres fixtures (via testcontainers) for STORE and
AUDIT requirement verification tests that need a live database.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


# ---------------------------------------------------------------------------
# Real Postgres fixtures for STORE / AUDIT requirement tests
# ---------------------------------------------------------------------------

_EVENT_STORE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id UUID PRIMARY KEY,
        event_type TEXT NOT NULL,
        schema_version TEXT NOT NULL DEFAULT '1.0.0',
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        actor_id TEXT,
        timestamp TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}',
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        audit_id UUID PRIMARY KEY,
        event_id UUID,
        action_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        timestamp TIMESTAMPTZ NOT NULL,
        detail JSONB NOT NULL DEFAULT '{}',
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE OR REPLACE FUNCTION audit_log_immutable()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only: UPDATE and DELETE are not permitted';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log",
    """
    CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
    """,
]


@pytest.fixture(scope="session")
def postgres_container():
    """Start a Postgres container for the test session."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed")

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session")
async def async_engine(postgres_container):
    """Create async SQLAlchemy engine pointed at the test Postgres container."""
    url = postgres_container.get_connection_url()
    async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(async_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def session_factory(async_engine):
    """Return an async_sessionmaker bound to the test Postgres engine."""
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session")
async def event_store_tables(async_engine):
    """Create events and audit_log tables with immutability trigger."""
    async with async_engine.begin() as conn:
        for stmt in _EVENT_STORE_STATEMENTS:
            await conn.execute(sa.text(stmt))
    yield async_engine


async def poll_row_count(
    session_factory,
    table: str,
    expected: int,
    timeout: float = 10.0,
) -> int:
    """Poll SELECT COUNT(*) FROM table until count >= expected or timeout."""
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        async with session_factory() as session:
            result = await session.execute(sa.text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
        if count >= expected:
            return count
        await asyncio.sleep(0.2)
    return count
