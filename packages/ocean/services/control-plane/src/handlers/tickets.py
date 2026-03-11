"""Control plane handlers for ticket lifecycle events.

handle_ticket_created: Routes new tickets, generates human_id, links tasks/alerts.
handle_ticket_updated: Validates state transitions, publishes state change events.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import structlog

from src.rules import (
    is_valid_transition,
    ticket_channel_for,
    ticket_priority_channels,
)

log = structlog.get_logger()

CATEGORY_PREFIXES: dict[str, str] = {
    "device_issue": "DEV",
    "patient_activation": "ACT",
    "clinical_support": "CLN",
    "engineering_it": "ENG",
}


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_ticket_created(event_data: dict, session, producer=None) -> None:
    """Handle incoming ticket creation request.

    Generates ticket_id, human_id from per-category sequence, writes ticket row,
    links bridge tables, and publishes ticket.created event.
    """
    payload = event_data.get("payload", {})
    category = payload.get("category", "device_issue")
    priority = payload.get("priority", "medium")
    patient_id = payload.get("patient_id", "")
    description = payload.get("description", "")
    task_ids = payload.get("task_ids", [])
    alert_ids = payload.get("alert_ids", [])
    timestamp_str = event_data.get("timestamp", "")

    ticket_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    ts = _parse_ts(timestamp_str) if timestamp_str else now

    # Generate human-readable ID from per-category sequence
    prefix = CATEGORY_PREFIXES.get(category, "TKT")
    seq_result = await session.execute(
        sa.text(f"SELECT nextval('ticket_seq_{category}')")
    )
    seq_val = seq_result.scalar_one()
    human_id = f"{prefix}-{seq_val:05d}"

    # Upsert ticket row
    await session.execute(
        sa.text(
            "INSERT INTO tickets "
            "  (ticket_id, human_id, category, priority, status, patient_id, "
            "   description, created_at, updated_at, correlation_id, last_event_id) "
            "VALUES "
            "  (:ticket_id, :human_id, :category, :priority, 'open', :patient_id, "
            "   :description, :created_at, :updated_at, :correlation_id, :event_id) "
            "ON CONFLICT (ticket_id) DO UPDATE SET "
            "  updated_at = EXCLUDED.updated_at, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE tickets.updated_at < EXCLUDED.updated_at"
        ),
        {
            "ticket_id": ticket_id,
            "human_id": human_id,
            "category": category,
            "priority": priority,
            "patient_id": patient_id,
            "description": description,
            "created_at": ts,
            "updated_at": now,
            "correlation_id": event_data.get("correlation_id", ""),
            "event_id": event_data.get("event_id", ""),
        },
    )

    # Link tasks
    for tid in task_ids:
        await session.execute(
            sa.text(
                "INSERT INTO ticket_tasks (ticket_id, task_id, linked_at) "
                "VALUES (:ticket_id, :task_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "task_id": tid, "linked_at": now},
        )

    # Link alerts
    for aid in alert_ids:
        await session.execute(
            sa.text(
                "INSERT INTO ticket_alerts (ticket_id, alert_id, linked_at) "
                "VALUES (:ticket_id, :alert_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "alert_id": aid, "linked_at": now},
        )

    log.info("ticket_created", ticket_id=ticket_id, human_id=human_id)

    if producer:
        channel = ticket_channel_for(category)
        crosspost = ticket_priority_channels(priority)
        ticket_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "ticket.created",
            "schema_version": "1.0.0",
            "timestamp": now.isoformat(),
            "source_system": "control-plane",
            "entity_id": ticket_id,
            "entity_type": "ticket",
            "correlation_id": event_data.get("correlation_id", ""),
            "payload": {
                "ticket_id": ticket_id,
                "human_id": human_id,
                "category": category,
                "priority": priority,
                "patient_id": patient_id,
                "description": description,
                "status": "open",
                "channel": channel,
                "crosspost_channels": crosspost,
                "task_ids": task_ids,
                "alert_ids": alert_ids,
            },
        }
        await producer.publish("ocean.tickets", ticket_event)


async def handle_ticket_updated(event_data: dict, session, producer=None) -> None:
    """Handle ticket state transitions.

    Validates transition legality, updates DB, publishes ticket.updated.
    On resolution, also publishes ticket.resolved.
    """
    payload = event_data.get("payload", {})
    ticket_id = event_data.get("entity_id", "")
    new_status = payload.get("new_status", "")
    new_priority = payload.get("priority")
    waiting_reason = payload.get("waiting_reason")
    task_ids = payload.get("task_ids", [])
    alert_ids = payload.get("alert_ids", [])
    now = datetime.now(tz=timezone.utc)

    # Fetch current status
    result = await session.execute(
        sa.text("SELECT status FROM tickets WHERE ticket_id = :ticket_id"),
        {"ticket_id": ticket_id},
    )
    current_status = result.scalar_one_or_none()
    if current_status is None:
        log.warning("ticket_not_found", ticket_id=ticket_id)
        return

    # Validate transition
    if not is_valid_transition(current_status, new_status):
        log.warning(
            "invalid_ticket_transition",
            ticket_id=ticket_id,
            current=current_status,
            target=new_status,
        )
        return

    # Build UPDATE
    set_clauses = ["status = :new_status", "updated_at = :updated_at", "last_event_id = :event_id"]
    params: dict = {
        "ticket_id": ticket_id,
        "new_status": new_status,
        "updated_at": now,
        "event_id": event_data.get("event_id", ""),
    }

    if new_priority is not None:
        set_clauses.append("priority = :priority")
        params["priority"] = new_priority

    if waiting_reason is not None:
        set_clauses.append("waiting_reason = :waiting_reason")
        params["waiting_reason"] = waiting_reason
    elif new_status != "waiting":
        set_clauses.append("waiting_reason = NULL")

    await session.execute(
        sa.text(
            f"UPDATE tickets SET {', '.join(set_clauses)} WHERE ticket_id = :ticket_id"
        ),
        params,
    )

    # Link new tasks/alerts
    for tid in task_ids:
        await session.execute(
            sa.text(
                "INSERT INTO ticket_tasks (ticket_id, task_id, linked_at) "
                "VALUES (:ticket_id, :task_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "task_id": tid, "linked_at": now},
        )

    for aid in alert_ids:
        await session.execute(
            sa.text(
                "INSERT INTO ticket_alerts (ticket_id, alert_id, linked_at) "
                "VALUES (:ticket_id, :alert_id, :linked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {"ticket_id": ticket_id, "alert_id": aid, "linked_at": now},
        )

    log.info("ticket_updated", ticket_id=ticket_id, new_status=new_status)

    if producer:
        updated_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "ticket.updated",
            "schema_version": "1.0.0",
            "timestamp": now.isoformat(),
            "source_system": "control-plane",
            "entity_id": ticket_id,
            "entity_type": "ticket",
            "correlation_id": event_data.get("correlation_id", ""),
            "payload": {
                "ticket_id": ticket_id,
                "status": new_status,
                "priority": new_priority,
                "waiting_reason": waiting_reason,
            },
        }
        await producer.publish("ocean.tickets", updated_event)

        if new_status == "resolved":
            resolved_event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "ticket.resolved",
                "schema_version": "1.0.0",
                "timestamp": now.isoformat(),
                "source_system": "control-plane",
                "entity_id": ticket_id,
                "entity_type": "ticket",
                "correlation_id": event_data.get("correlation_id", ""),
                "payload": {
                    "ticket_id": ticket_id,
                    "status": "resolved",
                },
            }
            await producer.publish("ocean.tickets", resolved_event)
