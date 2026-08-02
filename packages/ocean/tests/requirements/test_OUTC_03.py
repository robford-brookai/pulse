"""OUTC-03: alert.resolved publishes outcome.recorded via control-plane.

Requirement: handle_alert_resolved publishes outcome.recorded to ocean.outcomes
with entity_type="alert" and resolution_type="resolved".
"""

from __future__ import annotations

import pytest
from utils import setup_service

setup_service("control-plane")

from src.handlers.outcomes import handle_alert_resolved


@pytest.mark.asyncio
async def test_alert_resolved_publishes_outcome(mock_publisher, mock_session):
    """handle_alert_resolved publishes outcome.recorded to ocean.outcomes."""
    event_data = {
        "event_id": "evt-a-001",
        "event_type": "alert.resolved",
        "entity_id": "alert-abc-123",
        "correlation_id": "corr-a-xyz",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "actor_id": "user-resolver",
        },
    }

    await handle_alert_resolved(event_data, mock_session, producer=mock_publisher)

    mock_publisher.publish.assert_called_once()
    topic, event = mock_publisher.publish.call_args[0]

    assert topic == "ocean.outcomes"
    assert event["event_type"] == "outcome.recorded"
    assert event["payload"]["entity_type"] == "alert"
    assert event["payload"]["entity_id"] == "alert-abc-123"
    assert event["payload"]["resolution_type"] == "resolved"
    assert event["payload"]["resolved_by"] == "user-resolver"
