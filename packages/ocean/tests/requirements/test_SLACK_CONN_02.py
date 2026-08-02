"""SLACK-CONN-02: Consumer group isolation, full event handler registry.

Verifies:
- consumer group.id is "slack-bot-worker" (not "agent-worker")
- EVENT_HANDLERS has all 11 event type keys
- lifecycle stub handlers call thread_manager.queue_update
"""

from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = pathlib.Path(__file__).parents[2]


def _import_consumer():
    """Import consumer module from slack-bot service (isolated from other src.* modules)."""
    svc_src = str(_ROOT / "services" / "slack-bot")
    mod_name = "slack_bot_consumer"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    saved_src_modules = {k: v for k, v in sys.modules.items() if k == "src" or k.startswith("src.")}
    for k in saved_src_modules:
        del sys.modules[k]

    if svc_src not in sys.path:
        sys.path.insert(0, svc_src)

    try:
        mod = importlib.import_module("src.consumer")
        sys.modules[mod_name] = mod
        return mod
    finally:
        pass


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


class TestConsumerGroupIsolation:
    """Verify slack-bot uses its own consumer group."""

    def test_group_id_is_slack_bot_worker(self):
        source = (_ROOT / "services" / "slack-bot" / "src" / "consumer.py").read_text()
        assert '"slack-bot-worker"' in source
        assert (
            '"agent-worker"' not in source
            or "agent-worker" in source.split("slack-bot-worker")[0] is False
        )


class TestEventHandlerRegistry:
    """Verify EVENT_HANDLERS has all 11 event type entries."""

    EXPECTED_EVENTS = [
        "task.created",
        "task.claimed",
        "task.completed",
        "ai.recommendation.generated",
        "ai.output.approved",
        "ai.output.rejected",
        "call.connected",
        "call.missed",
        "call.completed",
        "scenario.started",
        "scenario.completed",
    ]

    def test_all_event_handlers_registered(self):
        source = (_ROOT / "services" / "slack-bot" / "src" / "consumer.py").read_text()
        for event_type in self.EXPECTED_EVENTS:
            assert f'"{event_type}"' in source, f"Handler for {event_type} not found in consumer.py"


# ---------------------------------------------------------------------------
# Unit test: lifecycle handlers call thread_manager.queue_update
# ---------------------------------------------------------------------------


class TestLifecycleHandlers:
    """Verify lifecycle handlers call thread_manager.queue_update."""

    @pytest.fixture()
    def consumer_mod(self):
        return _import_consumer()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler_name,event_type",
        [
            ("handle_task_claimed", "task.claimed"),
            ("handle_task_completed", "task.completed"),
        ],
    )
    async def test_lifecycle_handler_queues_update(self, consumer_mod, handler_name, event_type):
        mock_thread_manager = AsyncMock()
        mock_thread_manager.queue_update = AsyncMock()
        mock_thread_manager.update_parent_status = AsyncMock()

        event_data = {
            "event_type": event_type,
            "entity_id": "task-test",
            "payload": {"task_id": "task-test"},
        }

        handler = getattr(consumer_mod, handler_name)
        await handler(
            event_data,
            slack_client=AsyncMock(),
            session_maker=MagicMock(),
            hasura_url="http://localhost:8090",
            publisher=AsyncMock(),
            thread_manager=mock_thread_manager,
        )

        mock_thread_manager.queue_update.assert_called_once()
        call_args = mock_thread_manager.queue_update.call_args
        assert call_args[0][0] == "task-test"  # task_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler_name,event_type",
        [
            ("handle_scenario_started", "scenario.started"),
            ("handle_scenario_completed", "scenario.completed"),
        ],
    )
    async def test_scenario_handler_posts_card_directly(
        self, consumer_mod, handler_name, event_type
    ):
        """Scenario handlers post cards directly to channel, not via thread_manager."""
        mock_slack = AsyncMock()
        mock_slack.chat_postMessage = AsyncMock(return_value={"ok": True})

        event_data = {
            "event_type": event_type,
            "entity_id": "smoke_test",
            "payload": {"scenario_name": "smoke_test", "patients": ["p1"]},
        }

        handler = getattr(consumer_mod, handler_name)
        await handler(
            event_data,
            slack_client=mock_slack,
            session_maker=MagicMock(),
            hasura_url="http://localhost:8090",
            publisher=AsyncMock(),
            thread_manager=AsyncMock(),
        )

        mock_slack.chat_postMessage.assert_called_once()
