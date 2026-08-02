"""ESC-04: Slack-bot escalation handlers with card updates and thread replies.

Verifies:
- escalation_thread_reply returns Block Kit blocks with ":arrow_up: *Priority Escalated*"
- unclaimed_critical_reply returns Block Kit blocks with ":rotating_light: *UNCLAIMED CRITICAL*"
- alert_card with escalated=True prepends "[ESCALATED]" to header text
- ticket_card with escalated=True replaces status badge with "[ESCALATED]"
- slack-bot consumer.py registers task.escalated and ticket.escalated handlers
- thread_manager.py has get_channel and get_message_ts for task lookup
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

SLACK_BOT_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "slack-bot"
CONSUMER_PATH = SLACK_BOT_ROOT / "src" / "consumer.py"
THREAD_MANAGER_PATH = SLACK_BOT_ROOT / "src" / "thread_manager.py"
CARDS_PATH = SLACK_BOT_ROOT / "src" / "cards.py"


def _load_cards_module() -> ModuleType:
    """Load cards.py via importlib to avoid sys.path conflicts."""
    spec = importlib.util.spec_from_file_location("slack_bot_cards", CARDS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_event_handler_keys(path: pathlib.Path) -> list[str]:
    """Parse EVENT_HANDLERS dict keys from source via AST."""
    source = path.read_text()
    tree = ast.parse(source)
    handler_keys: list[str] = []
    for node in ast.walk(tree):
        dict_value = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EVENT_HANDLERS":
                    dict_value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "EVENT_HANDLERS":
                dict_value = node.value
        if dict_value is not None and isinstance(dict_value, ast.Dict):
            for key in dict_value.keys:
                if isinstance(key, ast.Constant):
                    handler_keys.append(key.value)
    return handler_keys


# ---------------------------------------------------------------------------
# Source inspection tests
# ---------------------------------------------------------------------------


class TestEscalationSourceInspection:
    """ESC-04: Source-level verification of escalation wiring."""

    def test_consumer_has_task_escalated_handler(self):
        keys = _parse_event_handler_keys(CONSUMER_PATH)
        assert "task.escalated" in keys, (
            "EVENT_HANDLERS must contain 'task.escalated' key"
        )

    def test_consumer_has_ticket_escalated_handler(self):
        keys = _parse_event_handler_keys(CONSUMER_PATH)
        assert "ticket.escalated" in keys, (
            "EVENT_HANDLERS must contain 'ticket.escalated' key"
        )

    def test_thread_manager_has_get_channel(self):
        source = THREAD_MANAGER_PATH.read_text()
        assert "async def get_channel(" in source, (
            "ThreadManager must have get_channel(task_id) method"
        )

    def test_thread_manager_has_get_message_ts(self):
        source = THREAD_MANAGER_PATH.read_text()
        assert "async def get_message_ts(" in source, (
            "ThreadManager must have get_message_ts(task_id) method"
        )


# ---------------------------------------------------------------------------
# Card builder tests (use importlib to avoid sys.path pollution)
# ---------------------------------------------------------------------------


class TestEscalationCards:
    """ESC-04: Escalation card builder output validation."""

    def test_escalation_thread_reply_contains_priority_escalated(self):
        mod = _load_cards_module()

        blocks = mod.escalation_thread_reply(
            entity_type="task",
            old_priority="medium",
            new_priority="high",
            minutes_unclaimed=32,
            policy_name="auto_escalate_medium_1800s",
        )

        text = blocks[0]["text"]["text"]
        assert ":arrow_up: *Priority Escalated*" in text
        assert "32m" in text
        assert "medium" in text
        assert "high" in text
        assert "auto_escalate_medium_1800s" in text

    def test_unclaimed_critical_reply_contains_rotating_light(self):
        mod = _load_cards_module()

        blocks = mod.unclaimed_critical_reply(
            entity_type="task",
            entity_id="task-123",
            minutes_unclaimed=45,
            policy_name="critical_repeat_3600s",
        )

        text = blocks[0]["text"]["text"]
        assert ":rotating_light: *UNCLAIMED CRITICAL*" in text
        assert "task" in text
        assert "45m" in text
        assert "critical_repeat_3600s" in text

    def test_alert_card_escalated_header(self):
        mod = _load_cards_module()

        blocks = mod.alert_card(
            task_id="task-1",
            patient_hash="patient-1",
            alert_type="blood_pressure",
            severity="HIGH",
            timestamp="2026-03-16T00:00:00Z",
            ai_summary="Test",
            hasura_url="http://localhost",
            escalated=True,
        )

        header_text = blocks[0]["text"]["text"]
        assert "[ESCALATED]" in header_text

    def test_ticket_card_escalated_header(self):
        mod = _load_cards_module()

        blocks = mod.ticket_card(
            ticket_id="ticket-1",
            human_id="TK-001",
            category="device_issue",
            priority="high",
            status="open",
            description="Test",
            ai_summary="Test",
            escalated=True,
        )

        header_text = blocks[0]["text"]["text"]
        assert "[ESCALATED]" in header_text


# ---------------------------------------------------------------------------
# Handler behavior tests (load consumer module with proper sys.path)
# ---------------------------------------------------------------------------


def _load_consumer_module() -> ModuleType:
    """Load slack-bot consumer.py via importlib to avoid sys.path conflicts.

    The consumer imports from src.cards, src.ai_events, etc. We temporarily
    set sys.path so those relative imports resolve to slack-bot/src/.
    """
    # Save and clear ALL conflicting cached modules (including bare "src")
    saved = {}
    for key in list(sys.modules.keys()):
        if key == "src" or key.startswith("src."):
            saved[key] = sys.modules.pop(key)

    original_path = sys.path.copy()
    # Remove other service src dirs that may resolve "src.*" imports incorrectly
    services_root = str(pathlib.Path(__file__).resolve().parents[2] / "services")
    cleaned_path = [p for p in sys.path if not p.startswith(services_root)]
    cleaned_path.insert(0, str(SLACK_BOT_ROOT))
    sys.path = cleaned_path

    try:
        spec = importlib.util.spec_from_file_location(
            "slack_bot_consumer",
            CONSUMER_PATH,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path = original_path
        # Restore previously cached modules
        for key in list(sys.modules.keys()):
            if key == "src" or key.startswith("src."):
                del sys.modules[key]
        sys.modules.update(saved)


class TestHandleTaskEscalated:
    """ESC-04: handle_task_escalated handler behavior."""

    @pytest.mark.asyncio
    async def test_calls_chat_update_and_chat_postMessage(self):
        """Escalation handler updates card in place and posts thread reply."""
        handle_task_escalated = _load_consumer_module().handle_task_escalated

        slack_client = AsyncMock()
        thread_manager = AsyncMock()
        thread_manager.get_channel = AsyncMock(return_value="#ocean-alerts")
        thread_manager.get_message_ts = AsyncMock(return_value="1234567890.123456")
        thread_manager.get_thread_ts = AsyncMock(return_value="1234567890.123456")

        event_data = {
            "event_type": "task.escalated",
            "entity_id": "task-001",
            "payload": {
                "old_priority": "medium",
                "new_priority": "high",
                "minutes_unclaimed": 32,
                "policy_name": "auto_escalate_medium_1800s",
                "escalation_count": 1,
            },
        }

        await handle_task_escalated(
            event_data,
            slack_client=slack_client,
            session_maker=MagicMock(),
            hasura_url="http://localhost",
            thread_manager=thread_manager,
        )

        slack_client.chat_update.assert_called_once()
        slack_client.chat_postMessage.assert_called_once()

        call_kwargs = slack_client.chat_postMessage.call_args
        assert call_kwargs.kwargs["channel"] == "#ocean-alerts"

    @pytest.mark.asyncio
    async def test_posts_unclaimed_critical_to_ocean_critical(self):
        """When old=critical and new=critical, posts to #ocean-critical."""
        handle_task_escalated = _load_consumer_module().handle_task_escalated

        slack_client = AsyncMock()
        thread_manager = AsyncMock()
        thread_manager.get_channel = AsyncMock(return_value="#ocean-critical")
        thread_manager.get_message_ts = AsyncMock(return_value="1234567890.123456")
        thread_manager.get_thread_ts = AsyncMock(return_value="1234567890.123456")

        event_data = {
            "event_type": "task.escalated",
            "entity_id": "task-002",
            "payload": {
                "old_priority": "critical",
                "new_priority": "critical",
                "minutes_unclaimed": 60,
                "policy_name": "critical_repeat_3600s",
                "escalation_count": 2,
            },
        }

        await handle_task_escalated(
            event_data,
            slack_client=slack_client,
            session_maker=MagicMock(),
            hasura_url="http://localhost",
            thread_manager=thread_manager,
        )

        post_call = slack_client.chat_postMessage.call_args
        assert post_call.kwargs["channel"] == "#ocean-critical"
