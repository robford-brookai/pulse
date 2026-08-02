"""SLACK-CONN-04: slack_messages persistence and ThreadManager.

Verifies:
- scenario.started and scenario.completed are valid EventType values
- 0008 migration creates slack_messages with required columns and indexes
- ThreadManager.queue_update stores events in batch dict
- ThreadManager.store_parent_message persists to slack_messages (mock session)
- ThreadManager.get_thread_ts retrieves thread_ts by task_id (mock session)
"""
from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = pathlib.Path(__file__).parents[2]


def _import_thread_manager():
    """Import ThreadManager from slack-bot service (isolated from other src.* modules)."""
    svc_src = _ROOT / "services" / "slack-bot"
    if str(svc_src) not in sys.path:
        sys.path.insert(0, str(svc_src))
    mod_name = "slack_bot_thread_manager"
    if mod_name in sys.modules:
        return sys.modules[mod_name].ThreadManager
    spec = importlib.util.spec_from_file_location(mod_name, svc_src / "src" / "thread_manager.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod.ThreadManager


# ---------------------------------------------------------------------------
# Source-inspection: EventType includes scenario events
# ---------------------------------------------------------------------------


class TestScenarioEventTypes:
    """Verify scenario event types in ocean-events types.py."""

    def test_scenario_started_in_event_type(self):
        source = (_ROOT / "libs" / "ocean-events" / "src" / "ocean_events" / "types.py").read_text()
        assert '"scenario.started"' in source, "scenario.started missing from EventType"

    def test_scenario_completed_in_event_type(self):
        source = (_ROOT / "libs" / "ocean-events" / "src" / "ocean_events" / "types.py").read_text()
        assert '"scenario.completed"' in source, "scenario.completed missing from EventType"


# ---------------------------------------------------------------------------
# Source-inspection: 0008 migration
# ---------------------------------------------------------------------------


class TestSlackMessagesMigration:
    """Verify 0008 migration creates slack_messages with correct schema."""

    @pytest.fixture()
    def migration_source(self):
        path = _ROOT / "infra" / "postgres" / "versions" / "0008_slack_messages.py"
        assert path.exists(), "0008_slack_messages.py migration not found"
        return path.read_text()

    def test_creates_slack_messages_table(self, migration_source):
        assert "slack_messages" in migration_source

    @pytest.mark.parametrize("column", ["task_id", "channel", "message_ts", "thread_ts", "status", "created_at", "updated_at"])
    def test_has_required_column(self, migration_source, column):
        assert column in migration_source, f"Column {column} missing from migration"

    def test_has_task_id_index(self, migration_source):
        assert "idx_slack_messages_task_id" in migration_source

    def test_has_message_ts_index(self, migration_source):
        assert "idx_slack_messages_ts" in migration_source


# ---------------------------------------------------------------------------
# Unit tests: ThreadManager
# ---------------------------------------------------------------------------


class TestThreadManager:
    """Unit tests for ThreadManager class."""

    @pytest.fixture()
    def mock_slack_client(self):
        client = AsyncMock()
        client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234.5678"})
        client.chat_update = AsyncMock(return_value={"ok": True})
        return client

    @pytest.fixture()
    def mock_session(self):
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        session.commit = AsyncMock()
        return session

    @pytest.fixture()
    def mock_session_maker(self, mock_session):
        return MagicMock(return_value=mock_session)

    @pytest.fixture()
    def thread_manager(self, mock_slack_client, mock_session_maker):
        ThreadManager = _import_thread_manager()
        return ThreadManager(mock_slack_client, mock_session_maker)

    @pytest.mark.asyncio
    async def test_queue_update_stores_in_batch(self, thread_manager):
        await thread_manager.queue_update("task-1", {"event_type": "task.claimed", "data": "test"})
        assert "task-1" in thread_manager._batches
        assert len(thread_manager._batches["task-1"]) == 1

    @pytest.mark.asyncio
    async def test_store_parent_message(self, thread_manager, mock_session):
        await thread_manager.store_parent_message("task-1", "#ocean-critical", "1234.5678")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_thread_ts_returns_none_when_not_found(self, thread_manager, mock_session):
        result = await thread_manager.get_thread_ts("nonexistent-task")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_ts_returns_ts_when_found(self, thread_manager, mock_session):
        mock_row = MagicMock()
        mock_row.thread_ts = "9999.1111"
        mock_session.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))
        result = await thread_manager.get_thread_ts("task-1")
        assert result == "9999.1111"
