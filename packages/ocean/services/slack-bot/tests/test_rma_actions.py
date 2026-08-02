"""Tests for RMA Bolt action handlers (create RMA, modal submission, retry)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_action_body(action_id: str, value: str, user_id: str = "U12345"):
    return {
        "actions": [{"action_id": action_id, "value": value}],
        "user": {"id": user_id},
        "trigger_id": "trigger-rma-123",
        "container": {"channel_id": "C123", "message_ts": "1234567890.000"},
    }


class TestTicketCreateRmaAction:
    """ticket_create_rma opens modal with correct fields."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        import src.bolt_app as ba

        self.publisher = AsyncMock()
        self.session_maker = MagicMock()
        ba._publisher = self.publisher
        ba._session_maker = self.session_maker

        # Mock DB queries for patient lookup
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        self.session_maker.return_value = mock_ctx

        # Mock patient lookup (returns patient_id, device_id, order_id)
        patient_row = MagicMock()
        patient_row.patient_id = "pat-001"

        device_row = MagicMock()
        device_row.scalar_one_or_none = MagicMock(return_value="dev-001")

        order_row = MagicMock()
        order_row.scalar_one_or_none = MagicMock(return_value="ord-001")

        ticket_row = MagicMock()
        ticket_row.fetchone = MagicMock(return_value=patient_row)

        mock_session.execute = AsyncMock(
            side_effect=[ticket_row, order_row, device_row]
        )
        mock_session.commit = AsyncMock()
        self.mock_session = mock_session

        yield
        ba._publisher = None
        ba._session_maker = None

    async def test_opens_modal(self):
        from src.bolt_app import handle_ticket_create_rma

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_create_rma", "tkt-rma-001")

        await handle_ticket_create_rma(ack, body, client)

        ack.assert_called_once()
        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs["view"]
        assert view["callback_id"] == "rma_create_modal"

    async def test_modal_private_metadata_contains_ids(self):
        from src.bolt_app import handle_ticket_create_rma

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_create_rma", "tkt-rma-001")

        await handle_ticket_create_rma(ack, body, client)

        view = client.views_open.call_args.kwargs["view"]
        metadata = json.loads(view["private_metadata"])
        assert metadata["ticket_id"] == "tkt-rma-001"
        assert metadata["patient_id"] == "pat-001"
        assert metadata["device_id"] == "dev-001"
        assert metadata["order_id"] == "ord-001"


class TestRmaCreateModal:
    """rma_create_modal submission publishes correct event."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        import src.bolt_app as ba

        self.publisher = AsyncMock()
        ba._publisher = self.publisher
        yield
        ba._publisher = None

    async def test_publishes_rma_requested_event(self):
        from src.bolt_app import handle_rma_create_modal

        ack = AsyncMock()
        client = AsyncMock()
        metadata = json.dumps({
            "ticket_id": "tkt-rma-001",
            "patient_id": "pat-001",
            "device_id": "dev-001",
            "order_id": "ord-001",
        })
        body = {
            "user": {"id": "U12345"},
            "view": {
                "private_metadata": metadata,
                "state": {
                    "values": {
                        "reason_block": {
                            "reason_select": {
                                "selected_option": {"value": "defective"},
                            },
                        },
                    },
                },
            },
        }

        await handle_rma_create_modal(ack, body, client)

        ack.assert_called_once()
        self.publisher.publish.assert_called_once()
        topic, event = self.publisher.publish.call_args[0]
        assert topic == "ocean.tickets"
        assert event["event_type"] == "ticket.rma.requested"
        assert event["payload"]["ticket_id"] == "tkt-rma-001"
        assert event["payload"]["reason"] == "defective"


class TestRetryRma:
    """ticket_retry_rma re-opens RMA modal."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        import src.bolt_app as ba

        self.publisher = AsyncMock()
        self.session_maker = MagicMock()
        ba._publisher = self.publisher
        ba._session_maker = self.session_maker

        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        self.session_maker.return_value = mock_ctx

        patient_row = MagicMock()
        patient_row.patient_id = "pat-001"

        device_row = MagicMock()
        device_row.scalar_one_or_none = MagicMock(return_value="dev-001")

        order_row = MagicMock()
        order_row.scalar_one_or_none = MagicMock(return_value="ord-001")

        ticket_row = MagicMock()
        ticket_row.fetchone = MagicMock(return_value=patient_row)

        mock_session.execute = AsyncMock(
            side_effect=[ticket_row, order_row, device_row]
        )
        mock_session.commit = AsyncMock()

        yield
        ba._publisher = None
        ba._session_maker = None

    async def test_retry_opens_modal(self):
        from src.bolt_app import handle_ticket_retry_rma

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("ticket_retry_rma", "tkt-rma-001")

        await handle_ticket_retry_rma(ack, body, client)

        ack.assert_called_once()
        client.views_open.assert_called_once()
        view = client.views_open.call_args.kwargs["view"]
        assert view["callback_id"] == "rma_create_modal"
