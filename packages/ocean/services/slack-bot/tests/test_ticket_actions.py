"""Tests for ticket Bolt action handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _make_action_body(action_id: str, ticket_id: str, user_id: str = "U12345"):
    """Build a minimal Slack action body for testing."""
    return {
        "actions": [{"action_id": action_id, "value": ticket_id}],
        "user": {"id": user_id},
        "container": {"channel_id": "C123", "message_ts": "1234567890.000"},
    }


class TestTicketClaim:
    @pytest.fixture(autouse=True)
    def _setup_publisher(self):
        """Inject a mock publisher into bolt_app module."""
        import src.bolt_app as ba

        self.publisher = AsyncMock()
        ba._publisher = self.publisher
        yield
        ba._publisher = None

    async def test_publishes_update_requested_event(self):
        from src.bolt_app import handle_ticket_claim

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_claim", "tkt-001")
        await handle_ticket_claim(ack, body, client)
        ack.assert_called_once()
        self.publisher.publish.assert_called_once()
        event = self.publisher.publish.call_args[0][1]
        assert event["event_type"] == "ticket.update.requested"
        assert event["payload"]["new_status"] == "in_progress"

    async def test_updates_card_to_claimed(self):
        from src.bolt_app import handle_ticket_claim

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_claim", "tkt-001")
        await handle_ticket_claim(ack, body, client)
        client.chat_update.assert_called_once()
        call_kwargs = client.chat_update.call_args.kwargs
        assert "blocks" in call_kwargs


class TestTicketResolve:
    @pytest.fixture(autouse=True)
    def _setup_publisher(self):
        import src.bolt_app as ba

        self.publisher = AsyncMock()
        ba._publisher = self.publisher
        yield
        ba._publisher = None

    async def test_publishes_resolved_event(self):
        from src.bolt_app import handle_ticket_resolve

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_resolve", "tkt-001")
        await handle_ticket_resolve(ack, body, client)
        ack.assert_called_once()
        event = self.publisher.publish.call_args[0][1]
        assert event["payload"]["new_status"] == "resolved"


class TestTicketWait:
    @pytest.fixture(autouse=True)
    def _setup_publisher(self):
        import src.bolt_app as ba

        self.publisher = AsyncMock()
        ba._publisher = self.publisher
        yield
        ba._publisher = None

    async def test_opens_modal(self):
        from src.bolt_app import handle_ticket_wait

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_wait", "tkt-001")
        body["trigger_id"] = "trigger-123"
        await handle_ticket_wait(ack, body, client)
        ack.assert_called_once()
        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs["view"]
        assert view["callback_id"] == "ticket_wait_modal"
        assert view["private_metadata"] == "tkt-001"
