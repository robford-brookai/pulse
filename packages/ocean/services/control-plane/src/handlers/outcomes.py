"""Centralized outcome publishing for control-plane.

All resolution paths (task, ticket, alert, call) funnel through
build_outcome_event to produce a normalized outcome.recorded event
on the ocean.outcomes topic.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

log = structlog.get_logger()

_OUTCOME_NS = uuid.NAMESPACE_URL


def build_outcome_event(
    entity_type: str,
    entity_id: str,
    resolution_type: str,
    resolved_by: str,
    correlation_id: str,
    timestamp: str | None = None,
) -> dict:
    """Build an outcome.recorded BaseEvent envelope.

    Generates a deterministic outcome_id via uuid5 for idempotency.
    """
    outcome_id = str(uuid.uuid5(_OUTCOME_NS, f"outcome-{entity_id}-{resolution_type}"))
    ts = timestamp or datetime.now(tz=timezone.utc).isoformat()

    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "outcome.recorded",
        "schema_version": "1.0.0",
        "timestamp": ts,
        "source_system": "control-plane",
        "entity_id": outcome_id,
        "entity_type": "outcome",
        "correlation_id": correlation_id,
        "payload": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "resolution_type": resolution_type,
            "resolved_by": resolved_by,
            "resolved_at": ts,
        },
    }


async def handle_alert_resolved(event_data: dict, session, producer=None) -> None:
    """Handle alert.resolved: publish outcome.recorded for alert resolution."""
    payload = event_data.get("payload", {})
    alert_id = event_data.get("entity_id", "")
    resolution_type = payload.get("resolution_type", "resolved")
    resolved_by = payload.get("actor_id", "system")
    correlation_id = event_data.get("correlation_id", "")

    log.info(
        "alert_outcome_recording",
        alert_id=alert_id,
        resolution_type=resolution_type,
    )

    if producer:
        outcome_event = build_outcome_event(
            entity_type="alert",
            entity_id=alert_id,
            resolution_type=resolution_type,
            resolved_by=resolved_by,
            correlation_id=correlation_id,
            timestamp=event_data.get("timestamp"),
        )
        await producer.publish("ocean.outcomes", outcome_event)


async def handle_task_completed(event_data: dict, session, producer=None) -> None:
    """Handle task.completed: publish outcome.recorded for task resolution."""
    task_id = event_data.get("entity_id", "")
    payload = event_data.get("payload", {})
    resolved_by = payload.get("persona_id", "system")
    correlation_id = event_data.get("correlation_id", "")

    log.info("task_outcome_recording", task_id=task_id)

    if producer:
        outcome_event = build_outcome_event(
            entity_type="task",
            entity_id=task_id,
            resolution_type="resolved",
            resolved_by=resolved_by,
            correlation_id=correlation_id,
            timestamp=event_data.get("timestamp"),
        )
        await producer.publish("ocean.outcomes", outcome_event)


async def handle_call_completed(event_data: dict, session, producer=None) -> None:
    """Handle call.completed: publish outcome.recorded for completed call."""
    engagement_id = event_data.get("entity_id", "")
    payload = event_data.get("payload", {})
    resolved_by = payload.get("agent_id", "system")
    correlation_id = event_data.get("correlation_id", "")

    log.info("call_completed_outcome_recording", engagement_id=engagement_id)

    if producer:
        outcome_event = build_outcome_event(
            entity_type="call",
            entity_id=engagement_id,
            resolution_type="completed",
            resolved_by=resolved_by,
            correlation_id=correlation_id,
            timestamp=event_data.get("timestamp"),
        )
        await producer.publish("ocean.outcomes", outcome_event)


async def handle_call_missed(event_data: dict, session, producer=None) -> None:
    """Handle call.missed: publish outcome.recorded for missed call."""
    engagement_id = event_data.get("entity_id", "")
    payload = event_data.get("payload", {})
    resolved_by = payload.get("agent_id", "system")
    correlation_id = event_data.get("correlation_id", "")

    log.info("call_missed_outcome_recording", engagement_id=engagement_id)

    if producer:
        outcome_event = build_outcome_event(
            entity_type="call",
            entity_id=engagement_id,
            resolution_type="missed",
            resolved_by=resolved_by,
            correlation_id=correlation_id,
            timestamp=event_data.get("timestamp"),
        )
        await producer.publish("ocean.outcomes", outcome_event)
