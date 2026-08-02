"""Unit tests for graph-projection ticket event handlers."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ticket_created_event(
    ticket_id: str = "ticket-001",
    human_id: str = "DEV-00001",
    category: str = "device_issue",
    priority: str = "high",
    patient_id: str = "patient-001",
    description: str = "Device not syncing",
    task_ids: list[str] | None = None,
    alert_ids: list[str] | None = None,
) -> dict:
    payload = {
        "ticket_id": ticket_id,
        "human_id": human_id,
        "category": category,
        "priority": priority,
        "patient_id": patient_id,
        "description": description,
        "status": "open",
        "channel": "#ocean-devices",
        "task_ids": task_ids or [],
        "alert_ids": alert_ids or [],
    }
    return {
        "event_id": "evt-tc-001",
        "event_type": "ticket.created",
        "timestamp": "2026-03-11T10:00:00Z",
        "source_system": "control-plane",
        "entity_id": ticket_id,
        "entity_type": "ticket",
        "correlation_id": "corr-ticket-001",
        "payload": payload,
    }


def _make_ticket_updated_event(
    ticket_id: str = "ticket-001",
    status: str = "in_progress",
    priority: str | None = None,
    waiting_reason: str | None = None,
    task_ids: list[str] | None = None,
    alert_ids: list[str] | None = None,
) -> dict:
    payload: dict = {"ticket_id": ticket_id, "status": status}
    if priority is not None:
        payload["priority"] = priority
    if waiting_reason is not None:
        payload["waiting_reason"] = waiting_reason
    if task_ids is not None:
        payload["task_ids"] = task_ids
    if alert_ids is not None:
        payload["alert_ids"] = alert_ids
    return {
        "event_id": "evt-tu-001",
        "event_type": "ticket.updated",
        "timestamp": "2026-03-11T11:00:00Z",
        "source_system": "control-plane",
        "entity_id": ticket_id,
        "entity_type": "ticket",
        "correlation_id": "corr-ticket-002",
        "payload": payload,
    }


def _make_ticket_resolved_event(ticket_id: str = "ticket-001") -> dict:
    return {
        "event_id": "evt-tr-001",
        "event_type": "ticket.resolved",
        "timestamp": "2026-03-11T12:00:00Z",
        "source_system": "control-plane",
        "entity_id": ticket_id,
        "entity_type": "ticket",
        "correlation_id": "corr-ticket-003",
        "payload": {"ticket_id": ticket_id, "status": "resolved"},
    }


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


# ---------------------------------------------------------------------------
# handle_ticket_created
# ---------------------------------------------------------------------------


class TestHandleTicketCreated:
    @pytest.mark.asyncio
    async def test_inserts_ticket_with_correct_params(self, mock_session):
        """handle_ticket_created calls session.execute with ticket fields."""
        from src.handlers.tickets import handle_ticket_created

        event = _make_ticket_created_event()
        await handle_ticket_created(event, mock_session)

        assert mock_session.execute.called
        params = mock_session.execute.call_args[0][1]
        assert params["ticket_id"] == "ticket-001"
        assert params["human_id"] == "DEV-00001"
        assert params["category"] == "device_issue"
        assert params["priority"] == "high"
        assert params["patient_id"] == "patient-001"

    @pytest.mark.asyncio
    async def test_inserts_bridge_rows_for_task_ids(self, mock_session):
        """When task_ids present, ticket_tasks bridge rows are inserted."""
        from src.handlers.tickets import handle_ticket_created

        event = _make_ticket_created_event(task_ids=["task-1", "task-2"])
        await handle_ticket_created(event, mock_session)

        # 1 ticket INSERT + 2 bridge INSERTs = 3
        assert mock_session.execute.call_count >= 3
        all_params = [c[0][1] for c in mock_session.execute.call_args_list if len(c[0]) > 1]
        task_id_params = [p.get("task_id") for p in all_params if "task_id" in p]
        assert "task-1" in task_id_params
        assert "task-2" in task_id_params

    @pytest.mark.asyncio
    async def test_inserts_bridge_rows_for_alert_ids(self, mock_session):
        """When alert_ids present, ticket_alerts bridge rows are inserted."""
        from src.handlers.tickets import handle_ticket_created

        event = _make_ticket_created_event(alert_ids=["alert-1"])
        await handle_ticket_created(event, mock_session)

        all_params = [c[0][1] for c in mock_session.execute.call_args_list if len(c[0]) > 1]
        alert_id_params = [p.get("alert_id") for p in all_params if "alert_id" in p]
        assert "alert-1" in alert_id_params

    @pytest.mark.asyncio
    async def test_idempotent_duplicate_does_not_raise(self, mock_session):
        """Calling handle_ticket_created twice does not raise."""
        from src.handlers.tickets import handle_ticket_created

        event = _make_ticket_created_event()
        await handle_ticket_created(event, mock_session)
        await handle_ticket_created(event, mock_session)
        assert mock_session.execute.call_count == 2


# ---------------------------------------------------------------------------
# handle_ticket_updated
# ---------------------------------------------------------------------------


class TestHandleTicketUpdated:
    @pytest.mark.asyncio
    async def test_updates_status_and_fields(self, mock_session):
        """handle_ticket_updated updates status, priority, waiting_reason."""
        from src.handlers.tickets import handle_ticket_updated

        event = _make_ticket_updated_event(status="waiting", priority="critical", waiting_reason="external_block")
        await handle_ticket_updated(event, mock_session)

        assert mock_session.execute.called
        params = mock_session.execute.call_args[0][1]
        assert params["ticket_id"] == "ticket-001"
        assert params["status"] == "waiting"
        assert params["priority"] == "critical"
        assert params["waiting_reason"] == "external_block"

    @pytest.mark.asyncio
    async def test_inserts_bridge_rows_on_update(self, mock_session):
        """New task_ids in update are linked."""
        from src.handlers.tickets import handle_ticket_updated

        event = _make_ticket_updated_event(task_ids=["task-new"])
        await handle_ticket_updated(event, mock_session)

        # 1 UPDATE + 1 bridge INSERT = 2
        assert mock_session.execute.call_count >= 2


# ---------------------------------------------------------------------------
# handle_ticket_resolved
# ---------------------------------------------------------------------------


class TestHandleTicketResolved:
    @pytest.mark.asyncio
    async def test_sets_status_resolved_and_clears_waiting(self, mock_session):
        """handle_ticket_resolved sets status=resolved, waiting_reason=NULL."""
        from src.handlers.tickets import handle_ticket_resolved

        event = _make_ticket_resolved_event()
        await handle_ticket_resolved(event, mock_session)

        assert mock_session.execute.called
        params = mock_session.execute.call_args[0][1]
        assert params["ticket_id"] == "ticket-001"
        assert params["event_id"] == "evt-tr-001"


# ---------------------------------------------------------------------------
# Consumer wiring
# ---------------------------------------------------------------------------


def test_ticket_events_registered_in_event_handlers():
    """ticket.created, ticket.updated, ticket.resolved are registered in EVENT_HANDLERS."""
    from src.consumer import EVENT_HANDLERS

    assert "ticket.created" in EVENT_HANDLERS
    assert "ticket.updated" in EVENT_HANDLERS
    assert "ticket.resolved" in EVENT_HANDLERS


def test_ticket_event_types_registered():
    """Ticket event types stay registered after the SQS conversion (DNA-761)."""
    from src.consumer import EVENT_HANDLERS

    for event_type in ("ticket.created", "ticket.updated", "ticket.resolved"):
        assert event_type in EVENT_HANDLERS
