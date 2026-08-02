"""OUTC-01: task.completed publishes outcome.recorded to ocean.outcomes.

Requirement: When control-plane receives task.completed, it publishes
outcome.recorded with entity_type="task" and resolution_type="resolved".
"""

from __future__ import annotations

import pytest
from utils import setup_service

setup_service("control-plane")

from src.handlers.outcomes import handle_task_completed


@pytest.mark.asyncio
async def test_task_completed_publishes_outcome(mock_publisher, mock_session):
    """handle_task_completed publishes outcome.recorded to ocean.outcomes."""
    event_data = {
        "event_id": "evt-001",
        "event_type": "task.completed",
        "entity_id": "task-abc-123",
        "correlation_id": "corr-xyz",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {
            "persona_id": "persona-1",
            "persona_role": "care_coordinator",
        },
    }

    await handle_task_completed(event_data, mock_session, producer=mock_publisher)

    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args
    topic = call_args[0][0]
    event = call_args[0][1]

    assert topic == "ocean.outcomes"
    assert event["event_type"] == "outcome.recorded"
    assert event["source_system"] == "control-plane"
    assert event["payload"]["entity_type"] == "task"
    assert event["payload"]["entity_id"] == "task-abc-123"
    assert event["payload"]["resolution_type"] == "resolved"
    assert event["payload"]["resolved_by"] == "persona-1"


@pytest.mark.asyncio
async def test_task_completed_no_publish_without_producer(mock_session):
    """handle_task_completed does not raise when producer is None."""
    event_data = {
        "event_id": "evt-002",
        "event_type": "task.completed",
        "entity_id": "task-def-456",
        "correlation_id": "corr-def",
        "timestamp": "2026-03-15T12:00:00+00:00",
        "payload": {},
    }

    await handle_task_completed(event_data, mock_session, producer=None)
