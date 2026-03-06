"""Graph projection handlers for task events."""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_task_created(event_data: dict, session) -> None:
    """Project task.created — INSERT with ON CONFLICT DO UPDATE."""
    payload = event_data.get("payload", {})
    task_id = event_data.get("entity_id", "")
    now = datetime.now(tz=timezone.utc)
    ts = _parse_ts(event_data["timestamp"])

    await session.execute(
        sa.text(
            "INSERT INTO tasks "
            "    (task_id, alert_id, patient_id, task_type, priority, status, assigned_to, created_at, updated_at, last_event_id) "
            "VALUES "
            "    (:task_id, :alert_id, :patient_id, :task_type, :priority, 'open', :assigned_to, :created_at, :updated_at, :event_id) "
            "ON CONFLICT (task_id) DO UPDATE SET "
            "    status = EXCLUDED.status, "
            "    updated_at = EXCLUDED.updated_at, "
            "    last_event_id = EXCLUDED.last_event_id "
            "WHERE tasks.updated_at < EXCLUDED.updated_at"
        ),
        {
            "task_id": task_id,
            "alert_id": payload.get("alert_id", ""),
            "patient_id": payload.get("patient_id", ""),
            "task_type": payload.get("task_type", "unknown"),
            "priority": payload.get("priority", "normal"),
            "assigned_to": payload.get("assigned_to"),
            "created_at": ts,
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )
    log.info("task_projected", task_id=task_id)


async def handle_task_completed(event_data: dict, session) -> None:
    """Project task.completed — update status to 'completed'."""
    task_id = event_data.get("entity_id", "")
    now = datetime.now(tz=timezone.utc)
    await session.execute(
        sa.text(
            "UPDATE tasks SET status='completed', updated_at=:updated_at, last_event_id=:event_id "
            "WHERE task_id=:task_id"
        ),
        {"task_id": task_id, "updated_at": now, "event_id": event_data.get("event_id", "")},
    )
    log.info("task_completed", task_id=task_id)


async def handle_task_assigned(event_data: dict, session) -> None:
    """Project task.assigned — update assigned_to."""
    task_id = event_data.get("entity_id", "")
    now = datetime.now(tz=timezone.utc)
    payload = event_data.get("payload", {})
    await session.execute(
        sa.text(
            "UPDATE tasks SET assigned_to=:assigned_to, updated_at=:updated_at, last_event_id=:event_id "
            "WHERE task_id=:task_id"
        ),
        {
            "task_id": task_id,
            "assigned_to": payload.get("assigned_to"),
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )
    log.info("task_assigned", task_id=task_id)
