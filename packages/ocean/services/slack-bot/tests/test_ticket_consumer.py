"""Tests for ticket event consumer handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.consumer import (
    handle_ticket_created,
    handle_ticket_resolved,
    handle_ticket_updated,
)


@pytest.fixture
def slack_client():
    client = AsyncMock()
    client.chat_postMessage.return_value = {"ts": "1234567890.123456"}
    client.chat_update.return_value = {"ok": True}
    return client


@pytest.fixture
def session_maker():
    return MagicMock()


@pytest.fixture
def publisher():
    return AsyncMock()


@pytest.fixture
def thread_manager():
    tm = AsyncMock()
    tm.get_ticket_thread_ts.return_value = "1234567890.123456"
    tm.get_ticket_channel.return_value = "#device-issues"
    return tm


TICKET_CREATED_EVENT = {
    "event_type": "ticket.created",
    "entity_id": "tkt-001",
    "entity_type": "ticket",
    "correlation_id": "corr-001",
    "timestamp": "2026-03-13T10:00:00Z",
    "payload": {
        "ticket_id": "tkt-001",
        "human_id": "DEV-00042",
        "category": "device_issue",
        "priority": "high",
        "patient_id": "patient-xyz",
        "description": "Device not syncing",
        "status": "open",
        "channel": "#device-issues",
        "crosspost_channels": ["#ocean-critical"],
        "task_ids": ["task-1"],
        "alert_ids": ["alert-1"],
    },
}

TICKET_UPDATED_EVENT = {
    "event_type": "ticket.updated",
    "entity_id": "tkt-001",
    "payload": {
        "ticket_id": "tkt-001",
        "status": "in_progress",
        "priority": "high",
        "waiting_reason": None,
    },
}

TICKET_RESOLVED_EVENT = {
    "event_type": "ticket.resolved",
    "entity_id": "tkt-001",
    "payload": {
        "ticket_id": "tkt-001",
        "status": "resolved",
    },
}


class TestHandleTicketCreated:
    @patch("src.consumer.generate_summary_with_context", new_callable=AsyncMock)
    async def test_posts_card_to_channel(self, mock_summary, slack_client, session_maker, publisher, thread_manager):
        mock_summary.return_value = ("AI summary text", ["signal1"])
        await handle_ticket_created(
            TICKET_CREATED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        slack_client.chat_postMessage.assert_called()
        call_kwargs = slack_client.chat_postMessage.call_args_list[0].kwargs
        assert call_kwargs["channel"] == "#device-issues"
        assert "blocks" in call_kwargs

    @patch("src.consumer.generate_summary_with_context", new_callable=AsyncMock)
    async def test_crossposts_to_priority_channels(
        self, mock_summary, slack_client, session_maker, publisher, thread_manager
    ):
        mock_summary.return_value = ("AI summary text", ["signal1"])
        await handle_ticket_created(
            TICKET_CREATED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        # Primary post + 1 crosspost = 2 calls
        assert slack_client.chat_postMessage.call_count >= 2
        channels = [c.kwargs["channel"] for c in slack_client.chat_postMessage.call_args_list]
        assert "#ocean-critical" in channels

    @patch("src.consumer.generate_summary_with_context", new_callable=AsyncMock)
    async def test_stores_parent_message(self, mock_summary, slack_client, session_maker, publisher, thread_manager):
        mock_summary.return_value = ("AI summary text", [])
        await handle_ticket_created(
            TICKET_CREATED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        thread_manager.store_ticket_parent.assert_called_once_with(
            "tkt-001", "#device-issues", "1234567890.123456", event_ts="2026-03-13T10:00:00Z"
        )


class TestHandleTicketUpdated:
    async def test_updates_card(self, slack_client, session_maker, publisher, thread_manager):
        await handle_ticket_updated(
            TICKET_UPDATED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        slack_client.chat_update.assert_called_once()
        call_kwargs = slack_client.chat_update.call_args.kwargs
        assert call_kwargs["channel"] == "#device-issues"
        assert "blocks" in call_kwargs

    async def test_queues_thread_update(self, slack_client, session_maker, publisher, thread_manager):
        await handle_ticket_updated(
            TICKET_UPDATED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        thread_manager.queue_ticket_update.assert_called_once()


class TestHandleTicketResolved:
    async def test_updates_card_to_resolved(self, slack_client, session_maker, publisher, thread_manager):
        await handle_ticket_resolved(
            TICKET_RESOLVED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        slack_client.chat_update.assert_called_once()

    async def test_posts_resolution_summary_thread(self, slack_client, session_maker, publisher, thread_manager):
        await handle_ticket_resolved(
            TICKET_RESOLVED_EVENT,
            slack_client=slack_client,
            session_maker=session_maker,
            hasura_url="http://hasura",
            publisher=publisher,
            thread_manager=thread_manager,
        )
        # Should post thread reply with resolution summary
        post_calls = slack_client.chat_postMessage.call_args_list
        assert len(post_calls) >= 1
        thread_call = post_calls[0].kwargs
        assert "thread_ts" in thread_call
