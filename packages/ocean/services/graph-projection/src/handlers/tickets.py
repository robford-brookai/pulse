"""Graph projection handlers for ticket events."""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_ticket_created(event_data: dict, session) -> None:
    """Project ticket.created -- INSERT with ON CONFLICT DO UPDATE."""
    payload = event_data.get("payload", {})
    ticket_id = event_data.get("entity_id", "")
    now = datetime.now(tz=UTC)
    ts = _parse_ts(event_data["timestamp"])

    await session.execute(
        sa.text(
            "INSERT INTO tickets "
            "  (ticket_id, human_id, category, priority, status, patient_id, "
            "   description, waiting_reason, created_at, updated_at, "
            "   correlation_id, last_event_id) "
            "VALUES "
            "  (:ticket_id, :human_id, :category, :priority, :status, "
            "   :patient_id, :description, :waiting_reason, :created_at, "
            "   :updated_at, :correlation_id, :event_id) "
            "ON CONFLICT (ticket_id) DO UPDATE SET "
            "  status = EXCLUDED.status, "
            "  priority = EXCLUDED.priority, "
            "  waiting_reason = EXCLUDED.waiting_reason, "
            "  updated_at = EXCLUDED.updated_at, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE tickets.updated_at < EXCLUDED.updated_at"
        ),
        {
            "ticket_id": ticket_id,
            "human_id": payload.get("human_id", ""),
            "category": payload.get("category", ""),
            "priority": payload.get("priority", "medium"),
            "status": payload.get("status", "open"),
            "patient_id": payload.get("patient_id", ""),
            "description": payload.get("description", ""),
            "waiting_reason": payload.get("waiting_reason"),
            "created_at": ts,
            "updated_at": now,
            "correlation_id": event_data.get("correlation_id", ""),
            "event_id": event_data.get("event_id", ""),
        },
    )

    # Bridge table: ticket_tasks
    for tid in payload.get("task_ids", []):
        await session.execute(
            sa.text(
                "INSERT INTO ticket_tasks (ticket_id, task_id, linked_at) "
                "VALUES (:ticket_id, :task_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "task_id": tid, "linked_at": now},
        )

    # Bridge table: ticket_alerts
    for aid in payload.get("alert_ids", []):
        await session.execute(
            sa.text(
                "INSERT INTO ticket_alerts (ticket_id, alert_id, linked_at) "
                "VALUES (:ticket_id, :alert_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "alert_id": aid, "linked_at": now},
        )

    log.info("ticket_projected", ticket_id=ticket_id, human_id=payload.get("human_id"))


async def handle_ticket_updated(event_data: dict, session) -> None:
    """Project ticket.updated -- update status, priority, waiting_reason."""
    payload = event_data.get("payload", {})
    ticket_id = event_data.get("entity_id", "")
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "UPDATE tickets SET "
            "  status = :status, "
            "  priority = :priority, "
            "  waiting_reason = :waiting_reason, "
            "  updated_at = :updated_at, "
            "  last_event_id = :event_id "
            "WHERE ticket_id = :ticket_id AND updated_at < :updated_at"
        ),
        {
            "ticket_id": ticket_id,
            "status": payload.get("status", ""),
            "priority": payload.get("priority"),
            "waiting_reason": payload.get("waiting_reason"),
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )

    # Bridge table: new task links
    for tid in payload.get("task_ids", []):
        await session.execute(
            sa.text(
                "INSERT INTO ticket_tasks (ticket_id, task_id, linked_at) "
                "VALUES (:ticket_id, :task_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "task_id": tid, "linked_at": now},
        )

    # Bridge table: new alert links
    for aid in payload.get("alert_ids", []):
        await session.execute(
            sa.text(
                "INSERT INTO ticket_alerts (ticket_id, alert_id, linked_at) "
                "VALUES (:ticket_id, :alert_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "alert_id": aid, "linked_at": now},
        )

    log.info("ticket_updated", ticket_id=ticket_id)


async def handle_ticket_resolved(event_data: dict, session) -> None:
    """Project ticket.resolved -- set status to resolved, clear waiting_reason."""
    ticket_id = event_data.get("entity_id", "")
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "UPDATE tickets SET "
            "  status = 'resolved', "
            "  waiting_reason = NULL, "
            "  updated_at = :updated_at, "
            "  last_event_id = :event_id "
            "WHERE ticket_id = :ticket_id"
        ),
        {
            "ticket_id": ticket_id,
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )

    log.info("ticket_resolved", ticket_id=ticket_id)
