"""Unit tests for delivery.notify consumer handler and delivery action handlers."""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


def _make_delivery_notify_event(
    order_id: str = "ord-dlv-001",
    patient_id: str = "pat-dlv-001",
    device_type: str = "BP Monitor",
    channel: str = "#ocean-activation",
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "delivery.notify",
        "timestamp": "2026-03-14T12:00:00Z",
        "source_system": "control-plane",
        "entity_id": order_id,
        "entity_type": "fulfillment",
        "correlation_id": "corr-dlv-001",
        "payload": {
            "patient_id": patient_id,
            "order_id": order_id,
            "device_type": device_type,
            "days_since_consent": 14,
            "tracking_numbers": ["TRACK123"],
            "shipping_option": "standard",
            "active_alerts_count": 2,
            "device_history_count": 1,
            "channel": channel,
        },
    }


class TestDeliveryNotifyHandler:
    """Consumer handler for delivery.notify posts card to correct channel."""

    @pytest.mark.asyncio
    async def test_posts_delivery_card_to_channel(self):
        from src.consumer import handle_delivery_notify

        slack_client = AsyncMock()
        slack_client.chat_postMessage.return_value = {"ts": "1234567890.123"}
        thread_manager = AsyncMock()

        event = _make_delivery_notify_event()

        await handle_delivery_notify(
            event,
            slack_client=slack_client,
            session_maker=None,
            hasura_url="http://hasura.test",
            publisher=None,
            thread_manager=thread_manager,
        )

        slack_client.chat_postMessage.assert_called_once()
        call_kwargs = slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "#ocean-activation"
        assert "blocks" in call_kwargs

    @pytest.mark.asyncio
    async def test_stores_parent_message_for_claim_tracking(self):
        from src.consumer import handle_delivery_notify

        slack_client = AsyncMock()
        slack_client.chat_postMessage.return_value = {"ts": "1234567890.123"}
        thread_manager = AsyncMock()

        event = _make_delivery_notify_event()

        await handle_delivery_notify(
            event,
            slack_client=slack_client,
            session_maker=None,
            hasura_url="http://hasura.test",
            publisher=None,
            thread_manager=thread_manager,
        )

        thread_manager.store_parent_message.assert_called_once_with(
            "delivery:ord-dlv-001", "#ocean-activation", "1234567890.123", event_ts="2026-03-14T12:00:00Z"
        )

    @pytest.mark.asyncio
    async def test_event_handler_registration(self):
        from src.consumer import EVENT_HANDLERS

        assert "delivery.notify" in EVENT_HANDLERS
