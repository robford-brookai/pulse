"""Unit tests for LeaderElector — Postgres advisory lock leader election.

Each test mocks the AsyncEngine / connection so we verify lock SQL
and state transitions without touching a real database.
"""

from __future__ import annotations

import pathlib

# Add the module under test to sys.path (same pattern as test_resume_token).
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs

_SRC = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector" / "src"
sys.path.insert(0, str(_SRC))

from leader import LOCK_ID, LeaderElector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine_and_conn(scalar_return=True):
    """Return (engine, conn) mocks wired so engine.connect() → conn."""
    conn = AsyncMock()
    # execute returns a result whose .scalar() gives the advisory lock bool.
    result = MagicMock()
    result.scalar.return_value = scalar_return
    conn.execute.return_value = result
    # get_raw_connection is awaited to detach from pool.
    conn.get_raw_connection = AsyncMock(return_value=MagicMock())

    engine = AsyncMock()
    engine.connect.return_value = conn
    return engine, conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_succeeds():
    """When pg_try_advisory_lock returns True, is_leader becomes True."""
    engine, conn = _make_engine_and_conn(scalar_return=True)
    elector = LeaderElector(engine)

    with capture_logs() as logs:
        result = await elector.acquire()

    assert result is True
    assert elector.is_leader is True
    # Verify the lock SQL was called with the correct lock ID.
    conn.execute.assert_awaited_once()
    sql_arg = str(conn.execute.call_args[0][0])
    assert "pg_try_advisory_lock" in sql_arg
    params = conn.execute.call_args[0][1]
    assert params["lock_id"] == LOCK_ID
    # structlog event
    assert any(log["event"] == "leader_acquired" for log in logs)


@pytest.mark.asyncio
async def test_acquire_fails_standby():
    """When pg_try_advisory_lock returns False, we enter standby."""
    engine, conn = _make_engine_and_conn(scalar_return=False)
    elector = LeaderElector(engine)

    with capture_logs() as logs:
        result = await elector.acquire()

    assert result is False
    assert elector.is_leader is False
    # Connection should be closed since we didn't get the lock.
    conn.close.assert_awaited_once()
    assert any(log["event"] == "leader_standby" for log in logs)


@pytest.mark.asyncio
async def test_release_unlocks():
    """After acquiring, release() calls pg_advisory_unlock and closes conn."""
    engine, conn = _make_engine_and_conn(scalar_return=True)
    elector = LeaderElector(engine)
    await elector.acquire()

    # Reset call tracking so we can assert only release-phase calls.
    conn.execute.reset_mock()

    with capture_logs() as logs:
        await elector.release()

    assert elector.is_leader is False
    # Verify unlock SQL was called.
    conn.execute.assert_awaited_once()
    sql_arg = str(conn.execute.call_args[0][0])
    assert "pg_advisory_unlock" in sql_arg
    # Connection closed after unlock.
    conn.close.assert_awaited()
    assert any(log["event"] == "leader_released" for log in logs)


@pytest.mark.asyncio
async def test_acquire_when_already_leader():
    """Second acquire() returns True immediately without a DB call."""
    engine, conn = _make_engine_and_conn(scalar_return=True)
    elector = LeaderElector(engine)
    await elector.acquire()

    # Reset call tracking.
    engine.connect.reset_mock()
    conn.execute.reset_mock()

    result = await elector.acquire()

    assert result is True
    assert elector.is_leader is True
    # No new DB call should have been made.
    engine.connect.assert_not_awaited()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_db_error_returns_false():
    """DB error during acquire → returns False + logs leader_check_failed."""
    engine = AsyncMock()
    engine.connect.side_effect = RuntimeError("connection refused")
    elector = LeaderElector(engine)

    with capture_logs() as logs:
        result = await elector.acquire()

    assert result is False
    assert elector.is_leader is False
    assert any(log["event"] == "leader_check_failed" for log in logs)


@pytest.mark.asyncio
async def test_release_when_not_leader():
    """release() is a no-op when not currently the leader."""
    engine, conn = _make_engine_and_conn(scalar_return=False)
    elector = LeaderElector(engine)

    # Never acquired — release should do nothing.
    conn.execute.reset_mock()
    await elector.release()

    assert elector.is_leader is False
    conn.execute.assert_not_awaited()
    conn.close.assert_not_awaited()
