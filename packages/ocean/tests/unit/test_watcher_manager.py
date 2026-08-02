"""Unit tests for WatcherManager — concurrent watcher orchestration."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — add mongodb-connector root so ``from src.xxx`` imports work.
# We must mock external dependencies (ocean_broker, confluent_kafka, motor,
# sqlalchemy) that aren't installed in the test venv before importing.
# ---------------------------------------------------------------------------
_CONNECTOR_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector"
if str(_CONNECTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONNECTOR_ROOT))

# Stub out third-party modules that aren't available in the test environment.
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

from src.watcher_manager import WatcherManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fake_registry(names: list[str] | None = None) -> dict:
    """Return a transformer registry of MagicMock objects."""
    if names is None:
        names = ["alerts", "chatRooms", "activity"]
    return {n: MagicMock() for n in names}


def _make_manager(
    *,
    collections: list[str] | None = None,
    registry: dict | None = None,
) -> WatcherManager:
    """Build a WatcherManager with mocked dependencies."""
    if registry is None:
        registry = _make_fake_registry()
    return WatcherManager(
        db=MagicMock(),  # motor database mock
        publisher=MagicMock(),
        token_store=MagicMock(),
        db_session_factory=MagicMock(),
        transformer_registry=registry,
        collections=collections,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWatcherManagerStart:
    """Tests for start() creating the right set of tasks."""

    @pytest.mark.asyncio
    async def test_start_creates_tasks_for_all_collections(self):
        """One asyncio task per registered collection when no subset given."""
        registry = _make_fake_registry(["alerts", "chatRooms", "activity"])
        manager = _make_manager(registry=registry)
        shutdown = asyncio.Event()

        with patch("src.watcher_manager.CollectionWatcher") as MockWatcher:
            mock_watch = AsyncMock(side_effect=lambda se: se.wait())
            MockWatcher.return_value.watch = mock_watch

            await manager.start(shutdown)

            assert set(manager._tasks.keys()) == {"alerts", "chatRooms", "activity"}
            assert MockWatcher.call_count == 3

            # Cleanup — signal shutdown and let tasks finish.
            shutdown.set()
            await manager.stop()

    @pytest.mark.asyncio
    async def test_subset_collections(self):
        """Only requested collections get watchers."""
        registry = _make_fake_registry(["alerts", "chatRooms", "activity"])
        manager = _make_manager(collections=["alerts"], registry=registry)
        shutdown = asyncio.Event()

        with patch("src.watcher_manager.CollectionWatcher") as MockWatcher:
            mock_watch = AsyncMock(side_effect=lambda se: se.wait())
            MockWatcher.return_value.watch = mock_watch

            await manager.start(shutdown)

            assert list(manager._tasks.keys()) == ["alerts"]
            assert MockWatcher.call_count == 1

            shutdown.set()
            await manager.stop()


class TestWatcherManagerStop:
    """Tests for stop() gracefully cancelling tasks."""

    @pytest.mark.asyncio
    async def test_stop_cancels_all_tasks(self):
        """stop() cancels every task and clears internal dict."""
        manager = _make_manager()
        shutdown = asyncio.Event()

        with patch("src.watcher_manager.CollectionWatcher") as MockWatcher:
            mock_watch = AsyncMock(side_effect=lambda se: se.wait())
            MockWatcher.return_value.watch = mock_watch

            await manager.start(shutdown)
            assert len(manager._tasks) == 3

            await manager.stop()
            assert len(manager._tasks) == 0


class TestWatcherManagerValidation:
    """Tests for input validation."""

    def test_unknown_collection_raises(self):
        """Passing a collection not in the registry raises ValueError."""
        registry = _make_fake_registry(["alerts"])
        with pytest.raises(ValueError, match="Unknown collection"):
            _make_manager(collections=["bogus_collection"], registry=registry)


class TestWatcherManagerIsolation:
    """Tests for error isolation between watchers."""

    @pytest.mark.asyncio
    async def test_single_watcher_failure_does_not_crash_others(self):
        """If one watcher raises, the others keep running."""
        registry = _make_fake_registry(["alerts", "chatRooms"])
        manager = _make_manager(registry=registry)
        shutdown = asyncio.Event()

        call_count = 0

        async def _watch_alerts(se: asyncio.Event) -> None:
            """Simulate an immediate crash."""
            raise RuntimeError("alerts watcher boom")

        async def _watch_chat(se: asyncio.Event) -> None:
            """Stay alive until shutdown."""
            await se.wait()

        with patch("src.watcher_manager.CollectionWatcher") as MockWatcher:
            instances: list[MagicMock] = []

            def _make_watcher(**kwargs):
                m = MagicMock()
                col = kwargs.get("collection_name", "")
                if col == "alerts":
                    m.watch = AsyncMock(side_effect=_watch_alerts)
                else:
                    m.watch = AsyncMock(side_effect=_watch_chat)
                instances.append(m)
                return m

            MockWatcher.side_effect = _make_watcher

            await manager.start(shutdown)

            # Give the alerts watcher time to crash.
            await asyncio.sleep(0.05)

            # chatRooms task should still be running.
            chat_task = manager._tasks.get("chatRooms")
            assert chat_task is not None
            assert not chat_task.done(), "chatRooms watcher should still be alive"

            # alerts task crashed.
            alerts_task = manager._tasks.get("alerts")
            assert alerts_task is not None
            assert alerts_task.done(), "alerts watcher should have failed"

            shutdown.set()
            await manager.stop()
