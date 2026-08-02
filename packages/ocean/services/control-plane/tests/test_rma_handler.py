"""Unit tests for RMA request handler and return status update handler."""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


def _make_rma_requested_event(
    ticket_id: str = "tkt-rma-001",
    reason: str = "defective",
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "ticket.rma.requested",
        "timestamp": "2026-03-14T10:00:00Z",
        "source_system": "slack-bot",
        "entity_id": ticket_id,
        "entity_type": "ticket",
        "correlation_id": "corr-rma-001",
        "payload": {
            "ticket_id": ticket_id,
            "patient_id": "pat-001",
            "device_id": "dev-001",
            "order_id": "ord-001",
            "reason": reason,
        },
    }


def _make_return_updated_event(
    return_id: str = "ret-001",
    status: str = "shipped",
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "return.updated",
        "timestamp": "2026-03-14T11:00:00Z",
        "source_system": "impilo-connector",
        "entity_id": return_id,
        "entity_type": "return",
        "correlation_id": "corr-ret-001",
        "payload": {
            "return_id": return_id,
            "status": status,
            "patient_id": "pat-001",
        },
    }


def _mock_ticket_row(
    patient_id: str = "pat-001",
    category: str = "device_issue",
):
    result = MagicMock()
    row = MagicMock()
    row.patient_id = patient_id
    row.category = category
    result.fetchone.return_value = row
    return result


def _mock_fulfillment_row(order_id: str = "ord-001"):
    result = MagicMock()
    result.scalar_one_or_none.return_value = order_id
    return result


def _mock_device_row(device_id: str = "dev-001"):
    result = MagicMock()
    result.scalar_one_or_none.return_value = device_id
    return result


def _mock_return_ticket_row(ticket_id: str = "tkt-rma-001"):
    result = MagicMock()
    result.scalar_one_or_none.return_value = ticket_id
    return result


class TestHandleRmaRequested:
    """handle_rma_requested looks up patient data, calls create_rma, publishes events."""

    @pytest.mark.asyncio
    async def test_success_publishes_rma_created(self):
        from src.handlers.tickets import handle_rma_requested

        session = AsyncMock()
        # Mock sequence: ticket lookup, fulfillment lookup, device lookup, INSERT
        session.execute = AsyncMock(
            side_effect=[
                _mock_ticket_row(),
                _mock_fulfillment_row(),
                _mock_device_row(),
                MagicMock(),  # INSERT return row
            ]
        )
        producer = AsyncMock()
        event = _make_rma_requested_event()

        with (
            patch(
                "src.handlers.tickets.create_rma",
                new_callable=AsyncMock,
                return_value={"id": "ret-001", "status": "initiated"},
            ),
            patch.dict(
                os.environ,
                {"IMPILO_API_URL": "http://impilo.test", "IMPILO_API_KEY": "key-123"},
            ),
        ):
            await handle_rma_requested(event, session, producer=producer)

        assert producer.publish.called
        pub_event = producer.publish.call_args[0][1]
        assert pub_event["event_type"] == "ticket.rma.created"
        assert pub_event["payload"]["return_id"] == "ret-001"

    @pytest.mark.asyncio
    async def test_ticket_not_found_raises_for_redelivery(self):
        """An RMA request whose ticket row has not arrived must not be acknowledged (task 3.8).

        Returning here loses the RMA outright — the consumer commits, the message is gone,
        and no ticket.rma.failed is emitted. Raising leaves the message for redelivery;
        6.3's redrive policy bounds the retries into the per-consumer DLQ.
        """
        from src.handlers.tickets import PreconditionNotArrived, handle_rma_requested

        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        session.execute = AsyncMock(return_value=result)
        producer = AsyncMock()
        event = _make_rma_requested_event()

        with pytest.raises(PreconditionNotArrived):
            await handle_rma_requested(event, session, producer=producer)

        producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_device_issue_rejected(self):
        from src.handlers.tickets import handle_rma_requested

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_ticket_row(category="clinical_support"))
        producer = AsyncMock()
        event = _make_rma_requested_event()

        await handle_rma_requested(event, session, producer=producer)

        # Should not publish any event (no RMA for non-device_issue)
        producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_order_publishes_rma_failed(self):
        from src.handlers.tickets import handle_rma_requested

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _mock_ticket_row(),
                _mock_fulfillment_row(order_id=None),  # no fulfillment
                _mock_device_row(),
            ]
        )
        producer = AsyncMock()
        event = _make_rma_requested_event()

        await handle_rma_requested(event, session, producer=producer)

        pub_event = producer.publish.call_args[0][1]
        assert pub_event["event_type"] == "ticket.rma.failed"

    @pytest.mark.asyncio
    async def test_api_failure_publishes_rma_failed(self):
        import httpx
        from src.handlers.tickets import handle_rma_requested

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _mock_ticket_row(),
                _mock_fulfillment_row(),
                _mock_device_row(),
            ]
        )
        producer = AsyncMock()
        event = _make_rma_requested_event()

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with (
            patch(
                "src.handlers.tickets.create_rma",
                new_callable=AsyncMock,
                side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp),
            ),
            patch.dict(
                os.environ,
                {"IMPILO_API_URL": "http://impilo.test", "IMPILO_API_KEY": "key-123"},
            ),
        ):
            await handle_rma_requested(event, session, producer=producer)

        pub_event = producer.publish.call_args[0][1]
        assert pub_event["event_type"] == "ticket.rma.failed"


class TestHandleReturnStatusUpdate:
    """handle_return_status_update filters to milestone statuses and publishes ticket.rma.status."""

    @pytest.mark.asyncio
    async def test_milestone_status_publishes_rma_status(self):
        from src.handlers.tickets import handle_return_status_update

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_return_ticket_row("tkt-rma-001"))
        producer = AsyncMock()
        event = _make_return_updated_event(status="shipped")

        await handle_return_status_update(event, session, producer=producer)

        pub_event = producer.publish.call_args[0][1]
        assert pub_event["event_type"] == "ticket.rma.status"
        assert pub_event["payload"]["status"] == "shipped"
        assert pub_event["payload"]["ticket_id"] == "tkt-rma-001"

    @pytest.mark.asyncio
    async def test_non_milestone_status_skipped(self):
        from src.handlers.tickets import handle_return_status_update

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_return_ticket_row())
        producer = AsyncMock()
        event = _make_return_updated_event(status="processing")

        await handle_return_status_update(event, session, producer=producer)

        producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_ticket_link_raises_for_redelivery(self):
        """A milestone update whose `returns` row has not arrived must not be acknowledged.

        The row is written by handle_rma_requested while return.updated arrives from a
        connector, so the race is live (task 3.8). Raising leaves the message for
        redelivery; a return that never gets a ticket link dead-letters observably.
        """
        from src.handlers.tickets import PreconditionNotArrived, handle_return_status_update

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_return_ticket_row(ticket_id=None))
        producer = AsyncMock()
        event = _make_return_updated_event(status="shipped")

        with pytest.raises(PreconditionNotArrived):
            await handle_return_status_update(event, session, producer=producer)

        producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_milestone_statuses_accepted(self):
        from src.handlers.tickets import handle_return_status_update

        milestones = ["label_created", "shipped", "received", "inspected", "completed"]
        for status in milestones:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=_mock_return_ticket_row())
            producer = AsyncMock()
            event = _make_return_updated_event(status=status)

            await handle_return_status_update(event, session, producer=producer)

            assert producer.publish.called, f"Expected publish for milestone '{status}'"
