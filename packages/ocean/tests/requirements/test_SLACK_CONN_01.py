"""SLACK-CONN-01: Multi-topic subscription, priority channel routing, auth.test.

Verifies:
- consumer.TOPICS has 4 topics (ocean.tasks, ocean.ai-ops, ocean.interactions, ocean.ops)
- CHANNEL_MAP exists with CRITICAL/URGENT/ROUTINE keys
- main.py contains auth_test call
- handle_task_created posts to correct channel based on severity
"""

from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROOT = pathlib.Path(__file__).parents[2]


def _import_consumer():
    """Import consumer module from slack-bot service (isolated from other src.* modules).

    Uses sys.path manipulation to ensure slack-bot's src package is resolved
    for transitive imports (ai_events, ai_summary, cards, etc.).
    """
    svc_src = str(_ROOT / "services" / "slack-bot")
    mod_name = "slack_bot_consumer"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    # Temporarily prioritize slack-bot on sys.path and clear cached src modules
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
        # Don't restore old src modules — let the slack-bot ones stay for this test session
        pass


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


class TestMultiTopicSubscription:
    """Verify consumer subscribes to 4 topics."""

    def test_topics_count(self):
        source = (_ROOT / "services" / "slack-bot" / "src" / "consumer.py").read_text()
        assert "ocean.tasks" in source
        assert "ocean.ai-ops" in source
        assert "ocean.interactions" in source
        assert "ocean.ops" in source

    def test_channel_map_exists(self):
        source = (_ROOT / "services" / "slack-bot" / "src" / "consumer.py").read_text()
        assert "CHANNEL_MAP" in source
        assert "CRITICAL" in source
        assert "URGENT" in source
        assert "ROUTINE" in source

    def test_auth_test_in_main(self):
        source = (_ROOT / "services" / "slack-bot" / "src" / "main.py").read_text()
        assert "auth_test" in source, "main.py must call auth_test on startup"


# ---------------------------------------------------------------------------
# Unit test: priority channel routing
# ---------------------------------------------------------------------------


class TestPriorityChannelRouting:
    """Verify handle_task_created routes to correct channel by severity."""

    @pytest.fixture()
    def consumer_mod(self):
        return _import_consumer()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "severity,expected_channel",
        [
            ("CRITICAL", "#ocean-critical"),
            ("URGENT", "#ocean-urgent"),
            ("ROUTINE", "#ocean-routine"),
            ("LOW", "#ocean-alerts"),
        ],
    )
    async def test_routes_to_correct_channel(self, consumer_mod, severity, expected_channel):
        mock_slack = AsyncMock()
        mock_slack.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "111.222"})

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_maker = MagicMock(return_value=mock_session)

        mock_thread_manager = AsyncMock()
        mock_thread_manager.store_parent_message = AsyncMock()

        event_data = {
            "event_type": "task.created",
            "entity_id": "task-123",
            "timestamp": "2026-03-10T00:00:00Z",
            "payload": {
                "task_id": "task-123",
                "patient_id": "pat-abc",
                "task_type": "missed_reading",
                "priority": severity,
                "channel": "#old-channel",
                "alert_id": "alert-1",
            },
        }

        with patch.object(consumer_mod, "generate_summary_with_context", new_callable=AsyncMock) as mock_summary:
            mock_summary.return_value = ("AI summary text", ["sig-1"])
            await consumer_mod.handle_task_created(
                event_data,
                slack_client=mock_slack,
                session_maker=mock_session_maker,
                hasura_url="http://localhost:8090",
                publisher=AsyncMock(),
                thread_manager=mock_thread_manager,
            )

        posted_channel = mock_slack.chat_postMessage.call_args_list[0].kwargs.get("channel")
        assert posted_channel == expected_channel, f"Expected {expected_channel}, got {posted_channel}"

    @pytest.mark.asyncio
    async def test_stores_parent_message(self, consumer_mod):
        mock_slack = AsyncMock()
        mock_slack.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "111.222"})

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_maker = MagicMock(return_value=mock_session)

        mock_thread_manager = AsyncMock()
        mock_thread_manager.store_parent_message = AsyncMock()

        event_data = {
            "event_type": "task.created",
            "entity_id": "task-456",
            "timestamp": "2026-03-10T00:00:00Z",
            "payload": {
                "task_id": "task-456",
                "patient_id": "pat-xyz",
                "task_type": "missed_reading",
                "priority": "CRITICAL",
                "channel": "#old",
                "alert_id": "alert-2",
            },
        }

        with patch.object(consumer_mod, "generate_summary_with_context", new_callable=AsyncMock) as mock_summary:
            mock_summary.return_value = ("AI summary", [])
            await consumer_mod.handle_task_created(
                event_data,
                slack_client=mock_slack,
                session_maker=mock_session_maker,
                hasura_url="http://localhost:8090",
                publisher=AsyncMock(),
                thread_manager=mock_thread_manager,
            )

        mock_thread_manager.store_parent_message.assert_called_once()
        call_args = mock_thread_manager.store_parent_message.call_args
        assert call_args[0][0] == "task-456"  # task_id
        assert call_args[0][1] == "#ocean-critical"  # channel
        assert call_args[0][2] == "111.222"  # message_ts
