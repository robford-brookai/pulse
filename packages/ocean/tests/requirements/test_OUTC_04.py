"""OUTC-04: call.completed/call.missed publish outcome.recorded to ocean.outcomes.

Requirement: handle_call_completed and handle_call_missed both publish
outcome.recorded with entity_type="call".
"""
from __future__ import annotations

import pytest

from utils import setup_service

setup_service("control-plane")

from src.handlers.outcomes import handle_call_completed, handle_call_missed  # noqa: E402


@pytest.mark.asyncio
async def test_call_completed_publishes_outcome(mock_publisher, mock_session):
    """handle_call_completed publishes outcome.recorded with resolution_type=completed."""
    event_data = {
        "event_id": "evt-c-001",
        "event_type": "call.completed",
        "entity_id": "eng-abc-123",
        "correlation_id": "corr-c-xyz",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "agent_id": "agent-1",
        },
    }

    await handle_call_completed(event_data, mock_session, producer=mock_publisher)

    mock_publisher.publish.assert_called_once()
    topic, event = mock_publisher.publish.call_args[0]

    assert topic == "ocean.outcomes"
    assert event["event_type"] == "outcome.recorded"
    assert event["payload"]["entity_type"] == "call"
    assert event["payload"]["entity_id"] == "eng-abc-123"
    assert event["payload"]["resolution_type"] == "completed"


@pytest.mark.asyncio
async def test_call_missed_publishes_outcome(mock_publisher, mock_session):
    """handle_call_missed publishes outcome.recorded with resolution_type=missed."""
    event_data = {
        "event_id": "evt-c-002",
        "event_type": "call.missed",
        "entity_id": "eng-def-456",
        "correlation_id": "corr-c-def",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "agent_id": "agent-2",
        },
    }

    await handle_call_missed(event_data, mock_session, producer=mock_publisher)

    mock_publisher.publish.assert_called_once()
    topic, event = mock_publisher.publish.call_args[0]

    assert topic == "ocean.outcomes"
    assert event["event_type"] == "outcome.recorded"
    assert event["payload"]["entity_type"] == "call"
    assert event["payload"]["entity_id"] == "eng-def-456"
    assert event["payload"]["resolution_type"] == "missed"
