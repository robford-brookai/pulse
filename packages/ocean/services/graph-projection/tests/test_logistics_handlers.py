"""Unit tests for graph-projection logistics event handlers."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fulfillment_event(
    order_id: str = "ORD-001",
    patient_id: str = "sha256_patient_abc",
    status: str = "shipped",
    shipping_option: str = "standard",
    tracking_numbers: list | None = None,
    order_items: list | None = None,
    devices: list | None = None,
) -> dict:
    return {
        "event_id": "evt-ful-001",
        "event_type": "fulfillment.updated",
        "entity_type": "fulfillment",
        "entity_id": order_id,
        "timestamp": "2026-03-13T10:00:00Z",
        "source_system": "impilo",
        "correlation_id": "corr-ful-001",
        "payload": {
            "order_id": order_id,
            "patient_id": patient_id,
            "status": status,
            "shipping_option": shipping_option,
            "tracking_numbers": tracking_numbers or ["1Z999AA10123456784"],
            "order_items": order_items or [{"sku": "BP-MONITOR", "qty": 1}],
            "devices": devices or [{"device_id": "dev-001", "name": "BP Monitor"}],
        },
    }


def _make_return_event(
    return_id: str = "RET-001",
    patient_id: str = "sha256_patient_abc",
    device_id: str = "dev-001",
    order_id: str = "ORD-001",
    status: str = "initiated",
    reason: str = "defective",
) -> dict:
    return {
        "event_id": "evt-ret-001",
        "event_type": "return.updated",
        "entity_type": "return",
        "entity_id": return_id,
        "timestamp": "2026-03-13T11:00:00Z",
        "source_system": "impilo",
        "correlation_id": "corr-ret-001",
        "payload": {
            "return_id": return_id,
            "patient_id": patient_id,
            "device_id": device_id,
            "order_id": order_id,
            "status": status,
            "reason": reason,
            "raw_payload": {"original": "impilo_data", "return_id": return_id},
        },
    }


def _make_device_associated_event(
    patient_id: str = "sha256_patient_abc",
    device_id: str = "dev-001",
    device_name: str = "BP Monitor",
    order_id: str = "ORD-001",
) -> dict:
    return {
        "event_id": "evt-da-001",
        "event_type": "device.associated",
        "entity_type": "device_association",
        "entity_id": device_id,
        "timestamp": "2026-03-13T12:00:00Z",
        "source_system": "impilo",
        "correlation_id": "corr-da-001",
        "payload": {
            "patient_id": patient_id,
            "device_id": device_id,
            "device_name": device_name,
            "order_id": order_id,
        },
    }


def _make_device_disassociated_event(
    patient_id: str = "sha256_patient_abc",
    device_id: str = "dev-001",
    device_name: str = "BP Monitor",
) -> dict:
    return {
        "event_id": "evt-dd-001",
        "event_type": "device.disassociated",
        "entity_type": "device_association",
        "entity_id": device_id,
        "timestamp": "2026-03-13T13:00:00Z",
        "source_system": "impilo",
        "correlation_id": "corr-dd-001",
        "payload": {
            "patient_id": patient_id,
            "device_id": device_id,
            "device_name": device_name,
        },
    }


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


# ---------------------------------------------------------------------------
# handle_fulfillment_updated
# ---------------------------------------------------------------------------

class TestHandleFulfillmentUpdated:
    @pytest.mark.asyncio
    async def test_inserts_fulfillment_with_correct_params(self, mock_session):
        """handle_fulfillment_updated upserts a fulfillments row with all fields."""
        from src.handlers.logistics import handle_fulfillment_updated

        event = _make_fulfillment_event()
        await handle_fulfillment_updated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "INSERT INTO fulfillments" in sql_text
        assert "ON CONFLICT" in sql_text
        assert params["order_id"] == "ORD-001"
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["status"] == "shipped"
        assert params["shipping_option"] == "standard"
        # JSONB fields should be serialized strings
        assert json.loads(params["tracking_numbers"]) == ["1Z999AA10123456784"]
        assert json.loads(params["order_items"]) == [{"sku": "BP-MONITOR", "qty": 1}]
        assert json.loads(params["devices"]) == [{"device_id": "dev-001", "name": "BP Monitor"}]

    @pytest.mark.asyncio
    async def test_idempotent_upsert_does_not_raise(self, mock_session):
        """Repeated fulfillment.updated calls for same order_id do not raise."""
        from src.handlers.logistics import handle_fulfillment_updated

        event = _make_fulfillment_event()
        await handle_fulfillment_updated(event, mock_session)
        await handle_fulfillment_updated(event, mock_session)
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_sql_has_updated_at_guard(self, mock_session):
        """ON CONFLICT clause includes WHERE updated_at < EXCLUDED.updated_at guard."""
        from src.handlers.logistics import handle_fulfillment_updated

        event = _make_fulfillment_event()
        await handle_fulfillment_updated(event, mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "WHERE fulfillments.updated_at < EXCLUDED.updated_at" in sql_text


# ---------------------------------------------------------------------------
# handle_return_updated
# ---------------------------------------------------------------------------

class TestHandleReturnUpdated:
    @pytest.mark.asyncio
    async def test_inserts_return_with_correct_params(self, mock_session):
        """handle_return_updated upserts a returns row with raw_payload."""
        from src.handlers.logistics import handle_return_updated

        event = _make_return_event()
        await handle_return_updated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "INSERT INTO returns" in sql_text
        assert "ON CONFLICT" in sql_text
        assert params["return_id"] == "RET-001"
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["device_id"] == "dev-001"
        assert params["status"] == "initiated"
        assert params["reason"] == "defective"
        # raw_payload should be serialized JSONB
        expected_raw = {"original": "impilo_data", "return_id": "RET-001"}
        assert json.loads(params["raw_payload"]) == expected_raw

    @pytest.mark.asyncio
    async def test_sql_has_updated_at_guard(self, mock_session):
        """ON CONFLICT clause includes WHERE guard."""
        from src.handlers.logistics import handle_return_updated

        event = _make_return_event()
        await handle_return_updated(event, mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "WHERE returns.updated_at < EXCLUDED.updated_at" in sql_text


# ---------------------------------------------------------------------------
# handle_device_associated
# ---------------------------------------------------------------------------

class TestHandleDeviceAssociated:
    @pytest.mark.asyncio
    async def test_inserts_device_association_active(self, mock_session):
        """handle_device_associated upserts with status='active'."""
        from src.handlers.logistics import handle_device_associated

        event = _make_device_associated_event()
        await handle_device_associated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "INSERT INTO device_associations" in sql_text
        assert "ON CONFLICT" in sql_text
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["device_id"] == "dev-001"
        assert params["device_name"] == "BP Monitor"

    @pytest.mark.asyncio
    async def test_reactivation_clears_removed_at(self, mock_session):
        """ON CONFLICT sets status='active' and removed_at=NULL."""
        from src.handlers.logistics import handle_device_associated

        event = _make_device_associated_event()
        await handle_device_associated(event, mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "status = 'active'" in sql_text
        assert "removed_at = NULL" in sql_text


# ---------------------------------------------------------------------------
# handle_device_disassociated
# ---------------------------------------------------------------------------

class TestHandleDeviceDisassociated:
    @pytest.mark.asyncio
    async def test_updates_device_to_removed(self, mock_session):
        """handle_device_disassociated sets status='removed' and removed_at."""
        from src.handlers.logistics import handle_device_disassociated

        # Simulate UPDATE returning 1 row affected
        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_session.execute = AsyncMock(return_value=result_mock)

        event = _make_device_disassociated_event()
        await handle_device_disassociated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "UPDATE device_associations" in sql_text
        assert "status = 'removed'" in sql_text
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["device_id"] == "dev-001"

    @pytest.mark.asyncio
    async def test_noop_when_no_matching_row(self, mock_session):
        """No-op (no crash) when device not found -- mock returns rowcount=0."""
        from src.handlers.logistics import handle_device_disassociated

        # Simulate UPDATE returning 0 rows
        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_session.execute = AsyncMock(return_value=result_mock)

        event = _make_device_disassociated_event()
        # Should not raise
        await handle_device_disassociated(event, mock_session)
        assert mock_session.execute.called


# ---------------------------------------------------------------------------
# Consumer wiring
# ---------------------------------------------------------------------------

def test_logistics_events_registered_in_event_handlers():
    """All 4 logistics event types are registered in EVENT_HANDLERS."""
    from src.consumer import EVENT_HANDLERS

    assert "fulfillment.updated" in EVENT_HANDLERS
    assert "return.updated" in EVENT_HANDLERS
    assert "device.associated" in EVENT_HANDLERS
    assert "device.disassociated" in EVENT_HANDLERS


def test_ocean_logistics_in_topics():
    """ocean.logistics is in the consumer TOPICS list."""
    from src.consumer import TOPICS

    assert "ocean.logistics" in TOPICS
