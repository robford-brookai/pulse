"""OUTC-02: ticket.resolved publishes outcome.recorded to ocean.outcomes.

Requirement: When handle_ticket_updated resolves a ticket (new_status="resolved"),
it publishes both ticket.resolved to ocean.tickets AND outcome.recorded to ocean.outcomes.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import setup_service

setup_service("control-plane")

from src.handlers.tickets import handle_ticket_updated  # noqa: E402


@pytest.mark.asyncio
async def test_ticket_resolved_publishes_outcome(mock_publisher, mock_session):
    """handle_ticket_updated with resolved status publishes outcome.recorded."""
    # Mock session.execute to return current status "in_progress" (valid -> resolved)
    status_result = MagicMock()
    status_result.scalar_one_or_none = MagicMock(return_value="in_progress")
    mock_session.execute = AsyncMock(return_value=status_result)

    event_data = {
        "event_id": "evt-t-001",
        "event_type": "ticket.update.requested",
        "entity_id": "ticket-abc-123",
        "correlation_id": "corr-t-xyz",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "new_status": "resolved",
            "actor_id": "user-1",
        },
    }

    await handle_ticket_updated(event_data, mock_session, producer=mock_publisher)

    # Should have been called at least 3 times:
    # 1. ticket.updated to ocean.tickets
    # 2. ticket.resolved to ocean.tickets
    # 3. outcome.recorded to ocean.outcomes
    calls = mock_publisher.publish.call_args_list
    assert len(calls) >= 3, f"Expected at least 3 publish calls, got {len(calls)}"

    topics = [c[0][0] for c in calls]
    events = [c[0][1] for c in calls]

    # Find outcome.recorded call
    outcome_calls = [
        (t, e) for t, e in zip(topics, events)
        if t == "ocean.outcomes" and e.get("event_type") == "outcome.recorded"
    ]
    assert len(outcome_calls) == 1, "Expected exactly 1 outcome.recorded publish to ocean.outcomes"

    _, outcome_event = outcome_calls[0]
    assert outcome_event["payload"]["entity_type"] == "ticket"
    assert outcome_event["payload"]["entity_id"] == "ticket-abc-123"
    assert outcome_event["payload"]["resolution_type"] == "resolved"


@pytest.mark.asyncio
async def test_ticket_non_resolved_no_outcome(mock_publisher, mock_session):
    """handle_ticket_updated with non-resolved status does NOT publish outcome.recorded."""
    status_result = MagicMock()
    status_result.scalar_one_or_none = MagicMock(return_value="open")
    mock_session.execute = AsyncMock(return_value=status_result)

    event_data = {
        "event_id": "evt-t-002",
        "event_type": "ticket.update.requested",
        "entity_id": "ticket-def-456",
        "correlation_id": "corr-t-def",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "new_status": "in_progress",
        },
    }

    await handle_ticket_updated(event_data, mock_session, producer=mock_publisher)

    calls = mock_publisher.publish.call_args_list
    outcome_calls = [
        c for c in calls
        if c[0][0] == "ocean.outcomes"
    ]
    assert len(outcome_calls) == 0, "Should not publish outcome for non-resolved status"
