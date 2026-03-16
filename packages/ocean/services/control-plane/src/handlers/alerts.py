"""Control plane handler for alert.created events.

Evaluates routing rules, writes a task record to Postgres, and publishes
task.created + task.assigned events to ocean.tasks topic.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

from src.escalation import insert_escalation_state
from src.rules import channel_for, priority_for

log = structlog.get_logger()


async def handle_alert_created(event_data: dict, session, producer=None) -> None:
    """Handle alert.created events: evaluate rules, write task to DB, publish event."""
    payload = event_data.get("payload", {})
    alert_id = event_data.get("entity_id", "")
    patient_id = payload.get("patient_id", "")
    alert_type = payload.get("alert_type", "unknown")
    timestamp_str = event_data.get("timestamp", "")

    # Deterministic task_id derived from alert_id using uuid5
    task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"task-{alert_id}"))
    priority = priority_for(alert_type)
    now = datetime.now(tz=UTC)
    ts = _parse_ts(timestamp_str) if timestamp_str else now

    await session.execute(
        sa.text(
            "INSERT INTO tasks "
            "  (task_id, alert_id, patient_id, task_type, priority, status, created_at, updated_at, last_event_id) "
            "VALUES (:task_id, :alert_id, :patient_id, :task_type, :priority, 'open', :created_at, :updated_at, :event_id) "
            "ON CONFLICT (task_id) DO UPDATE SET "
            "  updated_at = EXCLUDED.updated_at, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE tasks.updated_at < EXCLUDED.updated_at"
        ),
        {
            "task_id": task_id,
            "alert_id": alert_id,
            "patient_id": patient_id,
            "task_type": alert_type,
            "priority": priority,
            "created_at": ts,
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )
    # Track for escalation
    await insert_escalation_state(session, "task", task_id, priority, ts)

    log.info("task_created", task_id=task_id, alert_id=alert_id, priority=priority, alert_type=alert_type)
    log.info(f"[TASK] Patient {patient_id}: task created ({alert_type}, priority={priority})")

    if producer:
        task_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "task.created",
            "schema_version": "1.0.0",
            "timestamp": now.isoformat(),
            "source_system": "control-plane",
            "entity_id": task_id,
            "entity_type": "task",
            "correlation_id": event_data.get("correlation_id", ""),
            "payload": {
                "task_id": task_id,
                "alert_id": alert_id,
                "patient_id": patient_id,
                "task_type": alert_type,
                "priority": priority,
                "severity": payload.get("severity", ""),
                "signal_type": payload.get("signal_type", ""),
                "channel": channel_for(alert_type),
            },
        }
        await producer.publish("ocean.tasks", task_event)

        assigned_to = payload.get("assigned_to")
        if assigned_to:
            assigned_event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "task.assigned",
                "schema_version": "1.0.0",
                "timestamp": now.isoformat(),
                "source_system": "control-plane",
                "entity_id": task_id,
                "entity_type": "task",
                "correlation_id": event_data.get("correlation_id", ""),
                "payload": {
                    "task_id": task_id,
                    "assigned_to": assigned_to,
                },
            }
            await producer.publish("ocean.tasks", assigned_event)
            log.info("task_assigned_published", task_id=task_id, assigned_to=assigned_to)


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
