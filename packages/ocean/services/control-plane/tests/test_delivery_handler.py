"""Unit tests for delivery notification handler."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


def _make_fulfillment_event(
    status: str = "delivered",
    patient_id: str = "pat-dlv-001",
    order_id: str = "ord-dlv-001",
    tracking_numbers: list[str] | None = None,
    shipping_option: str = "standard",
    devices: list[dict] | None = None,
) -> dict:
    if devices is None:
        devices = [{"device_name": "BP Monitor", "device_id": "dev-001"}]
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "fulfillment.updated",
        "timestamp": "2026-03-14T12:00:00Z",
        "source_system": "impilo-connector",
        "entity_id": order_id,
        "entity_type": "fulfillment",
        "correlation_id": "corr-dlv-001",
        "payload": {
            "order_id": order_id,
            "patient_id": patient_id,
            "status": status,
            "tracking_numbers": tracking_numbers or ["TRACK123"],
            "shipping_option": shipping_option,
            "devices": devices,
        },
    }


def _mock_patient_row(created_at=None):
    """Mock patient query result with created_at."""
    if created_at is None:
        created_at = datetime(2026, 3, 1, tzinfo=UTC)
    result = MagicMock()
    result.scalar_one_or_none.return_value = created_at
    return result


def _mock_alerts_count(count: int = 2):
    result = MagicMock()
    result.scalar_one.return_value = count
    return result


def _mock_device_history_count(count: int = 1):
    result = MagicMock()
    result.scalar_one.return_value = count
    return result


class TestHandleDeliveryNotification:
    """handle_delivery_notification enriches delivery events and publishes delivery.notify."""

    @pytest.mark.asyncio
    async def test_delivered_status_publishes_notification(self):
        from src.handlers.deliveries import handle_delivery_notification

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _mock_patient_row(),  # patient created_at
                _mock_alerts_count(2),  # active alerts
                _mock_device_history_count(1),  # device history
            ]
        )
        producer = AsyncMock()
        event = _make_fulfillment_event(status="delivered")

        await handle_delivery_notification(event, session, producer=producer)

        assert producer.publish.called
        pub_event = producer.publish.call_args[0][1]
        assert pub_event["event_type"] == "delivery.notify"
        payload = pub_event["payload"]
        assert payload["patient_id"] == "pat-dlv-001"
        assert payload["device_type"] == "BP Monitor"
        assert payload["active_alerts_count"] == 2
        assert payload["device_history_count"] == 1
        assert payload["tracking_numbers"] == ["TRACK123"]
        assert payload["shipping_option"] == "standard"
        assert payload["channel"] == "#ocean-activation"
        assert payload["order_id"] == "ord-dlv-001"

    @pytest.mark.asyncio
    async def test_non_delivered_status_skipped(self):
        from src.handlers.deliveries import handle_delivery_notification

        session = AsyncMock()
        producer = AsyncMock()
        event = _make_fulfillment_event(status="shipped")

        await handle_delivery_notification(event, session, producer=producer)

        producer.publish.assert_not_called()
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_patient_context_enrichment(self):
        from src.handlers.deliveries import handle_delivery_notification

        consent_date = datetime(2026, 3, 1, tzinfo=UTC)
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _mock_patient_row(created_at=consent_date),
                _mock_alerts_count(3),
                _mock_device_history_count(2),
            ]
        )
        producer = AsyncMock()
        event = _make_fulfillment_event()

        await handle_delivery_notification(event, session, producer=producer)

        payload = producer.publish.call_args[0][1]["payload"]
        assert payload["days_since_consent"] >= 13  # 2026-03-14 - 2026-03-01
        assert payload["active_alerts_count"] == 3
        assert payload["device_history_count"] == 2

    @pytest.mark.asyncio
    async def test_missing_patient_uses_safe_defaults(self):
        from src.handlers.deliveries import handle_delivery_notification

        session = AsyncMock()
        # patient not found (None), alerts default, device history default
        none_result = MagicMock()
        none_result.scalar_one_or_none.return_value = None
        zero_result = MagicMock()
        zero_result.scalar_one.return_value = 0
        session.execute = AsyncMock(
            side_effect=[none_result, zero_result, zero_result]
        )
        producer = AsyncMock()
        event = _make_fulfillment_event(
            devices=[],  # no devices in payload
        )

        await handle_delivery_notification(event, session, producer=producer)

        payload = producer.publish.call_args[0][1]["payload"]
        assert payload["device_type"] == "Unknown device"
        assert payload["days_since_consent"] == 0
        assert payload["active_alerts_count"] == 0
        assert payload["device_history_count"] == 0


class TestDeliveryChannelRouting:
    """delivery_channel_for returns #ocean-activation."""

    def test_delivery_channel_for_returns_activation(self):
        from src.rules import delivery_channel_for

        assert delivery_channel_for() == "#ocean-activation"
