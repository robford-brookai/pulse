"""OUTC-05: false_positive resolution publishes outcome.recorded with resolution_type=false_positive.

Requirement: handle_alert_resolved with payload.resolution_type="false_positive"
publishes outcome.recorded where resolution_type="false_positive", not a separate event type.
"""
from __future__ import annotations

import pytest

from utils import setup_service

setup_service("control-plane")

from src.handlers.outcomes import handle_alert_resolved  # noqa: E402


@pytest.mark.asyncio
async def test_false_positive_resolution_publishes_outcome(mock_publisher, mock_session):
    """handle_alert_resolved with false_positive publishes outcome with correct resolution_type."""
    event_data = {
        "event_id": "evt-fp-001",
        "event_type": "alert.resolved",
        "entity_id": "alert-fp-123",
        "correlation_id": "corr-fp-xyz",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "actor_id": "user-dismisser",
            "resolution_type": "false_positive",
        },
    }

    await handle_alert_resolved(event_data, mock_session, producer=mock_publisher)

    mock_publisher.publish.assert_called_once()
    topic, event = mock_publisher.publish.call_args[0]

    assert topic == "ocean.outcomes"
    assert event["event_type"] == "outcome.recorded"
    assert event["payload"]["entity_type"] == "alert"
    assert event["payload"]["resolution_type"] == "false_positive"
    assert event["payload"]["resolved_by"] == "user-dismisser"


@pytest.mark.asyncio
async def test_false_positive_uses_outcome_recorded_not_separate_type(mock_publisher, mock_session):
    """False-positive uses resolution_type field, not a separate event type."""
    event_data = {
        "event_id": "evt-fp-002",
        "event_type": "alert.resolved",
        "entity_id": "alert-fp-456",
        "correlation_id": "corr-fp-def",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "actor_id": "user-2",
            "resolution_type": "false_positive",
        },
    }

    await handle_alert_resolved(event_data, mock_session, producer=mock_publisher)

    topic, event = mock_publisher.publish.call_args[0]
    # Event type is always outcome.recorded, never alert.false_positive
    assert event["event_type"] == "outcome.recorded"
    assert "alert.false_positive" not in str(event)
