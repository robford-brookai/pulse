"""Unit tests for /healthz and /readyz probe endpoints.

Each test mocks ``app.state`` to simulate different leader / watcher /
token-freshness states without running the full lifespan.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — same pattern as test_watcher_manager.py
# ---------------------------------------------------------------------------
_CONNECTOR_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector"
if str(_CONNECTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONNECTOR_ROOT))

# Stub third-party modules not available in the test environment.
for _mod_name in (
    "ocean_broker",
    "confluent_kafka",
    "motor",
    "motor.motor_asyncio",
    "pymongo",
    "pymongo.errors",
    "bson",
    "bson.json_util",
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Import the endpoint functions from main, but build a separate app
# without the real lifespan (which installs signal handlers that fail
# outside the main thread).
from src.main import healthz, readyz, _LATEST_TOKEN_SQL  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


# Minimal app with the same routes but no lifespan side-effects.
app = FastAPI(lifespan=_noop_lifespan)
app.get("/healthz")(healthz)
app.get("/readyz")(readyz)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _configure_state(
    *,
    is_leader: bool = False,
    manager_started: bool = False,
    latest_token_time: datetime | None = None,
    token_check_error: bool = False,
) -> None:
    """Patch ``app.state`` to simulate a specific replica state."""
    leader_mock = MagicMock()
    leader_mock.is_leader = is_leader
    app.state.leader = leader_mock
    app.state.manager_started = manager_started

    # Build a session factory that returns a mock session.
    session_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar.return_value = latest_token_time
    session_mock.execute.return_value = result_mock

    if token_check_error:
        session_mock.execute.side_effect = RuntimeError("db gone")

    # async context-manager mock for `async with session_factory() as s:`
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = session_mock
    ctx.__aexit__.return_value = False
    factory.return_value = ctx

    app.state.session_factory = factory


# ---------------------------------------------------------------------------
# Use a plain TestClient (sync) since the probes don't depend on lifespan.
# We bypass lifespan by patching app.state directly.
# ---------------------------------------------------------------------------


class TestHealthz:
    """Liveness probe — always 200."""

    def test_healthz_always_200(self):
        """GET /healthz returns 200 regardless of leader/watcher state."""
        # Don't configure any state — endpoint should still return 200.
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_healthz_returns_200_even_when_standby(self):
        """GET /healthz returns 200 even when this replica is not leader."""
        _configure_state(is_leader=False, manager_started=False)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        assert resp.status_code == 200


class TestReadyz:
    """Readiness probe — 200 only when leader + watchers + fresh token."""

    def test_readyz_leader_with_watchers_and_fresh_token(self):
        """Returns 200 when leader, watchers active, token recent."""
        fresh_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        _configure_state(
            is_leader=True,
            manager_started=True,
            latest_token_time=fresh_time,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True

    def test_readyz_not_leader(self):
        """Returns 503 with leader: false when not the leader."""
        _configure_state(is_leader=False, manager_started=False)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert body["checks"]["leader"] is False

    def test_readyz_stale_token(self):
        """Returns 503 with token_fresh: false when last token > 60s old."""
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        _configure_state(
            is_leader=True,
            manager_started=True,
            latest_token_time=stale_time,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert body["checks"]["token_fresh"] is False
        # Leader and watchers should still be True.
        assert body["checks"]["leader"] is True
        assert body["checks"]["watchers"] is True

    def test_readyz_no_watchers(self):
        """Returns 503 with watchers: false when manager not started."""
        _configure_state(is_leader=True, manager_started=False)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert body["checks"]["watchers"] is False

    def test_readyz_no_token_rows(self):
        """Returns 503 when there are no resume token rows at all."""
        _configure_state(
            is_leader=True,
            manager_started=True,
            latest_token_time=None,  # no rows
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert body["checks"]["token_fresh"] is False

    def test_readyz_token_check_db_error(self):
        """DB error during token check → token_fresh is false, not a crash."""
        _configure_state(
            is_leader=True,
            manager_started=True,
            token_check_error=True,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert body["checks"]["token_fresh"] is False
