"""Tests for /ocean ticket modal and message action — Slack ticket creation intake."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest


@pytest.fixture()
def mock_publisher():
    pub = AsyncMock()
    return pub


@pytest.fixture()
def _inject_publisher(mock_publisher):
    """Inject mock publisher into bolt_app module."""
    from src import bolt_app as ba

    original = ba._publisher
    ba._publisher = mock_publisher
    yield
    ba._publisher = original


class TestTicketSubcommand:
    """Test /ocean ticket opens modal via views_open."""

    @pytest.mark.asyncio
    async def test_ticket_subcommand_opens_modal(self):
        from src.slash_commands import handle_ocean_command

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()
        body = {
            "text": "ticket",
            "trigger_id": "trigger-abc",
            "user_id": "U123",
        }

        await handle_ocean_command(ack=ack, body=body, respond=respond, client=client)

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()
        call_kwargs = client.views_open.call_args[1]
        assert call_kwargs["trigger_id"] == "trigger-abc"
        view = call_kwargs["view"]
        assert view["callback_id"] == "ticket_create_modal"
        # Must have 5 input blocks: category, description, priority, patient_id, related_ticket
        input_blocks = [b for b in view["blocks"] if b["type"] == "input"]
        assert len(input_blocks) == 5
        # respond should NOT be called for ticket subcommand
        respond.assert_not_awaited()


class TestTicketModalSubmission:
    """Test modal submission publishes event and sends ephemeral."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_inject_publisher")
    async def test_ticket_modal_submission_publishes_event(self, mock_publisher):
        from src.bolt_app import handle_ticket_create_modal

        ack = AsyncMock()
        client = AsyncMock()
        body = {
            "user": {"id": "U456"},
            "view": {
                "private_metadata": "{}",
                "state": {
                    "values": {
                        "category_block": {
                            "category_select": {
                                "selected_option": {"value": "device_issue"},
                            },
                        },
                        "description_block": {
                            "description_input": {"value": "Device not syncing"},
                        },
                        "priority_block": {
                            "priority_select": {
                                "selected_option": {"value": "high"},
                            },
                        },
                        "patient_block": {
                            "patient_input": {"value": "PAT-001"},
                        },
                        "related_block": {
                            "related_input": {"value": "DEV-00041"},
                        },
                    },
                },
            },
        }

        await handle_ticket_create_modal(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        mock_publisher.publish.assert_awaited_once()
        call_args = mock_publisher.publish.call_args
        topic = call_args[0][0] if call_args[0] else call_args[1].get("topic")
        assert topic == "ocean.tickets"

        event = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("event")
        assert event["event_type"] == "ticket.create.requested"
        assert event["source_system"] == "slack-bot"
        assert event["entity_type"] == "ticket"
        assert event["payload"]["category"] == "device_issue"
        assert event["payload"]["description"] == "Device not syncing"
        assert event["payload"]["priority"] == "high"
        assert event["payload"]["patient_id"] == "PAT-001"
        assert event["payload"]["related_ticket_human_id"] == "DEV-00041"
        assert event["payload"]["creator_slack_id"] == "U456"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_inject_publisher")
    async def test_ticket_modal_submission_sends_ephemeral(self, mock_publisher):
        from src.bolt_app import handle_ticket_create_modal

        ack = AsyncMock()
        client = AsyncMock()
        body = {
            "user": {"id": "U456"},
            "view": {
                "private_metadata": "{}",
                "state": {
                    "values": {
                        "category_block": {
                            "category_select": {
                                "selected_option": {"value": "device_issue"},
                            },
                        },
                        "description_block": {
                            "description_input": {"value": "Test desc"},
                        },
                        "priority_block": {
                            "priority_select": {
                                "selected_option": {"value": "medium"},
                            },
                        },
                        "patient_block": {
                            "patient_input": {"value": ""},
                        },
                        "related_block": {
                            "related_input": {"value": ""},
                        },
                    },
                },
            },
        }

        await handle_ticket_create_modal(ack=ack, body=body, client=client)

        client.chat_postEphemeral.assert_awaited_once()
        call_kwargs = client.chat_postEphemeral.call_args[1]
        text = call_kwargs["text"]
        # Must contain routing confirmation but NOT a human_id like DEV-00042
        assert "Ticket request submitted" in text
        assert "#ocean-devices" in text
        # Should NOT contain a ticket human_id
        assert "DEV-0" not in text
        assert "ACT-0" not in text


class TestMessageAction:
    """Test message action opens modal with pre-filled description."""

    @pytest.mark.asyncio
    async def test_message_action_opens_modal_prefilled(self):
        from src.bolt_app import handle_create_ocean_ticket_shortcut

        ack = AsyncMock()
        client = AsyncMock()
        client.chat_getPermalink = AsyncMock(return_value={"permalink": "https://slack.com/msg/123"})
        body = {
            "trigger_id": "trigger-xyz",
            "channel": {"id": "C123"},
            "message": {
                "ts": "1234567890.123456",
                "text": "Patient device is offline",
            },
        }

        await handle_create_ocean_ticket_shortcut(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()
        call_kwargs = client.views_open.call_args[1]
        view = call_kwargs["view"]
        assert view["callback_id"] == "ticket_create_modal"

        # Description block should have initial_value from message text
        desc_block = next(b for b in view["blocks"] if b.get("block_id") == "description_block")
        initial_value = desc_block["element"].get("initial_value", "")
        assert "Patient device is offline" in initial_value

    @pytest.mark.asyncio
    async def test_message_action_stores_permalink(self):
        from src.bolt_app import handle_create_ocean_ticket_shortcut

        ack = AsyncMock()
        client = AsyncMock()
        client.chat_getPermalink = AsyncMock(return_value={"permalink": "https://slack.com/archives/C123/p1234567890"})
        body = {
            "trigger_id": "trigger-xyz",
            "channel": {"id": "C123"},
            "message": {
                "ts": "1234567890.123456",
                "text": "Some message",
            },
        }

        await handle_create_ocean_ticket_shortcut(ack=ack, body=body, client=client)

        call_kwargs = client.views_open.call_args[1]
        view = call_kwargs["view"]
        metadata = json.loads(view["private_metadata"])
        assert metadata["source_message_url"] == "https://slack.com/archives/C123/p1234567890"
