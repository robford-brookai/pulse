"""Tests for lifecycle thread replies, organic batching, and parent status updates.

Plan 15-02 Task 1: Verifies ThreadManager posts consolidated Block Kit thread
replies with reply_broadcast=False, retries on missing parent, and
lifecycle_update_blocks builds structured sections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.cards import lifecycle_update_blocks
from src.thread_manager import ThreadManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_slack_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


@pytest.fixture()
def mock_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    session.commit = AsyncMock()
    return session


@pytest.fixture()
def mock_session_maker(mock_session):
    return MagicMock(return_value=mock_session)


@pytest.fixture()
def thread_manager(mock_slack_client, mock_session_maker):
    return ThreadManager(mock_slack_client, mock_session_maker)


# ---------------------------------------------------------------------------
# lifecycle_update_blocks
# ---------------------------------------------------------------------------


class TestLifecycleUpdateBlocks:
    """lifecycle_update_blocks builds structured Block Kit sections."""

    def test_single_claimed_update(self):
        updates = [{"type": "claimed", "actor": "Nurse Maria"}]
        blocks = lifecycle_update_blocks(updates)
        text = _extract_all_text(blocks)
        assert "claimed" in text.lower()
        assert "Nurse Maria" in text

    def test_single_ai_recommendation(self):
        updates = [
            {
                "type": "ai_recommendation",
                "action": "Schedule call",
                "confidence": "HIGH",
                "reasoning": "Patient missed 2 readings",
            }
        ]
        blocks = lifecycle_update_blocks(updates)
        text = _extract_all_text(blocks)
        assert "Schedule call" in text
        assert "HIGH" in text

    def test_single_call_outcome(self):
        updates = [{"type": "call_outcome", "outcome": "connected", "duration_seconds": 120}]
        blocks = lifecycle_update_blocks(updates)
        text = _extract_all_text(blocks)
        assert "connected" in text

    def test_multiple_updates_have_dividers(self):
        updates = [
            {"type": "claimed", "actor": "Nurse A"},
            {"type": "ai_recommendation", "action": "Call patient", "confidence": "MEDIUM"},
        ]
        blocks = lifecycle_update_blocks(updates)
        dividers = [b for b in blocks if b.get("type") == "divider"]
        assert len(dividers) >= 1

    def test_returns_list_of_dicts(self):
        blocks = lifecycle_update_blocks([{"type": "claimed", "actor": "Nurse A"}])
        assert isinstance(blocks, list)
        assert all(isinstance(b, dict) for b in blocks)

    def test_ai_approved_update(self):
        updates = [{"type": "ai_approved", "actor": "Dr. Smith"}]
        blocks = lifecycle_update_blocks(updates)
        text = _extract_all_text(blocks)
        assert "approved" in text.lower()

    def test_ai_rejected_update(self):
        updates = [{"type": "ai_rejected", "actor": "Dr. Smith", "reason": "Not appropriate"}]
        blocks = lifecycle_update_blocks(updates)
        text = _extract_all_text(blocks)
        assert "rejected" in text.lower()

    def test_call_missed_update(self):
        updates = [{"type": "call_outcome", "outcome": "missed"}]
        blocks = lifecycle_update_blocks(updates)
        text = _extract_all_text(blocks)
        assert "missed" in text


# ---------------------------------------------------------------------------
# ThreadManager._post_thread_reply
# ---------------------------------------------------------------------------


class TestPostThreadReply:
    """_post_thread_reply posts consolidated Block Kit thread replies."""

    @pytest.mark.asyncio
    async def test_posts_with_thread_ts(self, thread_manager, mock_slack_client, mock_session):
        _setup_thread_lookup(mock_session, thread_ts="111.222", channel="#ocean-critical")
        updates = [{"type": "claimed", "actor": "Nurse A"}]
        await thread_manager._post_thread_reply("task-1", updates)
        mock_slack_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["thread_ts"] == "111.222"

    @pytest.mark.asyncio
    async def test_reply_broadcast_is_false(self, thread_manager, mock_slack_client, mock_session):
        _setup_thread_lookup(mock_session, thread_ts="111.222", channel="#ocean-critical")
        updates = [{"type": "claimed", "actor": "Nurse A"}]
        await thread_manager._post_thread_reply("task-1", updates)
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs.get("reply_broadcast") is False

    @pytest.mark.asyncio
    async def test_posts_blocks_from_lifecycle_update_blocks(self, thread_manager, mock_slack_client, mock_session):
        _setup_thread_lookup(mock_session, thread_ts="111.222", channel="#ocean-critical")
        updates = [{"type": "claimed", "actor": "Nurse B"}]
        await thread_manager._post_thread_reply("task-1", updates)
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert "blocks" in call_kwargs
        assert isinstance(call_kwargs["blocks"], list)

    @pytest.mark.asyncio
    async def test_retries_once_when_parent_not_found(self, thread_manager, mock_slack_client, mock_session):
        """If get_thread_ts returns None first, retries after 2s."""
        call_count = 0

        async def mock_get(task_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            return "111.222"

        thread_manager.get_thread_ts = mock_get
        # Also need channel lookup to succeed on retry
        _setup_channel_lookup(mock_session, channel="#ocean-critical")

        with patch("src.thread_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            updates = [{"type": "claimed", "actor": "Nurse A"}]
            await thread_manager._post_thread_reply("task-1", updates)
            mock_sleep.assert_called_once_with(2)

        assert call_count == 2
        mock_slack_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_parent_not_found_after_retry(self, thread_manager, mock_slack_client, mock_session):
        """If get_thread_ts returns None both times, skips posting."""

        async def mock_get(task_id):
            return None

        thread_manager.get_thread_ts = mock_get

        with patch("src.thread_manager.asyncio.sleep", new_callable=AsyncMock):
            updates = [{"type": "claimed", "actor": "Nurse A"}]
            await thread_manager._post_thread_reply("task-1", updates)

        mock_slack_client.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# ThreadManager._flush_after
# ---------------------------------------------------------------------------


class TestFlushAfter:
    """_flush_after waits delay then flushes pending batch."""

    @pytest.mark.asyncio
    async def test_flush_after_sleeps_then_posts(self, thread_manager, mock_slack_client, mock_session):
        _setup_thread_lookup(mock_session, thread_ts="111.222", channel="#ocean-critical")
        thread_manager._batches["task-1"] = [{"type": "claimed", "actor": "Nurse A"}]

        with patch("src.thread_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await thread_manager._flush_after("task-1", 5.0)
            mock_sleep.assert_called_once_with(5.0)

        mock_slack_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_after_clears_batch(self, thread_manager, mock_slack_client, mock_session):
        _setup_thread_lookup(mock_session, thread_ts="111.222", channel="#ocean-critical")
        thread_manager._batches["task-1"] = [{"type": "claimed", "actor": "Nurse A"}]

        with patch("src.thread_manager.asyncio.sleep", new_callable=AsyncMock):
            await thread_manager._flush_after("task-1", 3.0)

        assert "task-1" not in thread_manager._batches


# ---------------------------------------------------------------------------
# ThreadManager.update_parent_status
# ---------------------------------------------------------------------------


class TestUpdateParentStatus:
    """update_parent_status calls chat.update with status prefix in header."""

    @pytest.mark.asyncio
    async def test_calls_chat_update(self, thread_manager, mock_slack_client, mock_session):
        _setup_parent_lookup(mock_session, channel="#ocean-critical", message_ts="111.222")
        await thread_manager.update_parent_status("task-1", "CLAIMED")
        mock_slack_client.chat_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_update_includes_status_in_text(self, thread_manager, mock_slack_client, mock_session):
        _setup_parent_lookup(mock_session, channel="#ocean-critical", message_ts="111.222")
        await thread_manager.update_parent_status("task-1", "CLAIMED")
        call_kwargs = mock_slack_client.chat_update.call_args[1]
        assert "CLAIMED" in call_kwargs.get("text", "")


# ---------------------------------------------------------------------------
# Consumer handler tests (non-stub behavior)
# ---------------------------------------------------------------------------


class TestConsumerHandlers:
    """Verify handlers extract fields from payload and pass structured data."""

    @pytest.fixture()
    def deps(self, mock_slack_client, mock_session_maker):
        tm = ThreadManager(mock_slack_client, mock_session_maker)
        tm.queue_update = AsyncMock()
        tm.update_parent_status = AsyncMock()
        return {
            "slack_client": mock_slack_client,
            "session_maker": mock_session_maker,
            "hasura_url": "http://localhost:8090",
            "publisher": AsyncMock(),
            "thread_manager": tm,
        }

    @pytest.mark.asyncio
    async def test_handle_task_claimed_extracts_actor(self, deps):
        from src.consumer import handle_task_claimed

        event_data = {
            "event_type": "task.claimed",
            "entity_id": "task-1",
            "actor_id": "nurse-maria",
            "payload": {"task_id": "task-1", "persona_id": "nurse-maria", "persona_role": "RN"},
        }
        await handle_task_claimed(event_data, **deps)
        deps["thread_manager"].queue_update.assert_called_once()
        update = deps["thread_manager"].queue_update.call_args[0][1]
        assert update["type"] == "claimed"
        assert "nurse-maria" in str(update.get("actor", ""))

    @pytest.mark.asyncio
    async def test_handle_task_claimed_updates_parent_status(self, deps):
        from src.consumer import handle_task_claimed

        event_data = {
            "event_type": "task.claimed",
            "entity_id": "task-1",
            "payload": {"task_id": "task-1", "actor": "Nurse Maria"},
        }
        await handle_task_claimed(event_data, **deps)
        deps["thread_manager"].update_parent_status.assert_called_once_with("task-1", "CLAIMED")

    @pytest.mark.asyncio
    async def test_handle_task_completed_updates_parent_resolved(self, deps):
        from src.consumer import handle_task_completed

        event_data = {
            "event_type": "task.completed",
            "entity_id": "task-1",
            "payload": {"task_id": "task-1"},
        }
        await handle_task_completed(event_data, **deps)
        deps["thread_manager"].update_parent_status.assert_called_once_with("task-1", "RESOLVED")

    @pytest.mark.asyncio
    async def test_handle_ai_recommendation_extracts_fields(self, deps):
        from src.consumer import handle_ai_recommendation

        event_data = {
            "event_type": "ai.recommendation.generated",
            "entity_id": "task-1",
            "payload": {
                "task_id": "task-1",
                "action": "Schedule outreach call",
                "confidence": "HIGH",
                "reasoning": "Missed 2 readings",
            },
        }
        await handle_ai_recommendation(event_data, **deps)
        update = deps["thread_manager"].queue_update.call_args[0][1]
        assert update["type"] == "ai_recommendation"
        assert update["action"] == "Schedule outreach call"
        assert update["confidence"] == "HIGH"

    @pytest.mark.asyncio
    async def test_handle_call_event_extracts_outcome(self, deps):
        from src.consumer import handle_call_event

        event_data = {
            "event_type": "call.connected",
            "entity_id": "task-1",
            "payload": {"task_id": "task-1", "outcome": "connected", "duration_seconds": 180},
        }
        await handle_call_event(event_data, **deps)
        update = deps["thread_manager"].queue_update.call_args[0][1]
        assert update["type"] == "call_outcome"
        assert update["outcome"] == "connected"

    @pytest.mark.asyncio
    async def test_handle_scenario_started_posts_card_directly(self, deps):
        from src.consumer import handle_scenario_started

        event_data = {
            "event_type": "scenario.started",
            "entity_id": "smoke_test",
            "payload": {
                "scenario_name": "smoke_test",
                "patients": ["p1", "p2"],
                "flow_combos": ["alert->task", "task->call"],
            },
        }
        await handle_scenario_started(event_data, **deps)
        deps["slack_client"].chat_postMessage.assert_called_once()
        call_kwargs = deps["slack_client"].chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "#ocean-alerts"
        assert "blocks" in call_kwargs

    @pytest.mark.asyncio
    async def test_handle_scenario_completed_posts_card_directly(self, deps):
        from src.consumer import handle_scenario_completed

        event_data = {
            "event_type": "scenario.completed",
            "entity_id": "smoke_test",
            "payload": {
                "scenario_name": "smoke_test",
                "patients_count": 3,
                "alerts_generated": 5,
                "tasks_created": 5,
                "duration_seconds": 45.2,
            },
        }
        await handle_scenario_completed(event_data, **deps)
        deps["slack_client"].chat_postMessage.assert_called_once()
        call_kwargs = deps["slack_client"].chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "#ocean-alerts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_all_text(blocks: list[dict]) -> str:
    """Extract all text content from Block Kit blocks."""
    parts = []
    for b in blocks:
        if "text" in b and isinstance(b["text"], dict):
            parts.append(b["text"].get("text", ""))
        if "fields" in b:
            for f in b["fields"]:
                parts.append(f.get("text", ""))
    return " ".join(parts)


def _setup_thread_lookup(mock_session, *, thread_ts: str, channel: str):
    """Configure mock session to return thread_ts and channel for lookups."""
    row_thread = MagicMock()
    row_thread.thread_ts = thread_ts
    row_channel = MagicMock()
    row_channel.channel = channel

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(fetchone=MagicMock(return_value=row_thread))
        return MagicMock(fetchone=MagicMock(return_value=row_channel))

    mock_session.execute = AsyncMock(side_effect=side_effect)


def _setup_channel_lookup(mock_session, *, channel: str):
    """Configure mock session to return channel only."""
    row = MagicMock()
    row.channel = channel
    mock_session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row)))


def _setup_parent_lookup(mock_session, *, channel: str, message_ts: str):
    """Configure mock session to return channel and message_ts for parent lookup."""
    row = MagicMock()
    row.channel = channel
    row.message_ts = message_ts
    mock_session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row)))
