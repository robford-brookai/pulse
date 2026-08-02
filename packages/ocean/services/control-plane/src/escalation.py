"""Background escalation poller for unclaimed tasks and tickets.

Single-tier escalation: each unclaimed item escalates one priority level
per threshold breach. Critical items post an UNCLAIMED CRITICAL warning
instead of upgrading further.

State is persisted in task_escalation_state table and rehydrated on startup.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

from src.rules import PRIORITY_UPGRADE

log = structlog.get_logger()

ESCALATION_THRESHOLDS: dict[str, int] = {
    "critical": int(os.environ.get("ESCALATION_TIMEOUT_CRITICAL", "300")),
    "high": int(os.environ.get("ESCALATION_TIMEOUT_HIGH", "900")),
    "medium": int(os.environ.get("ESCALATION_TIMEOUT_MEDIUM", "1800")),
    "low": int(os.environ.get("ESCALATION_TIMEOUT_LOW", "3600")),
}

ESCALATION_ENABLED = os.environ.get("ESCALATION_ENABLED", "true").lower() == "true"
POLL_INTERVAL = int(os.environ.get("ESCALATION_POLL_INTERVAL", "60"))

# Statuses that indicate the item is no longer actionable
_TERMINAL_STATUSES = frozenset({"claimed", "completed", "resolved", "canceled"})


async def insert_escalation_state(
    session,
    entity_type: str,
    entity_id: str,
    priority: str,
    created_at: datetime,
) -> None:
    """Insert a row into task_escalation_state for tracking.

    Uses ON CONFLICT DO NOTHING so duplicate inserts are idempotent.
    """
    await session.execute(
        sa.text(
            "INSERT INTO task_escalation_state "
            "  (entity_type, entity_id, priority_at_creation, current_priority, created_at) "
            "VALUES (:entity_type, :entity_id, :priority, :priority, :created_at) "
            "ON CONFLICT (entity_type, entity_id) DO NOTHING"
        ),
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "priority": priority,
            "created_at": created_at,
        },
    )


async def remove_escalation_state(session, entity_type: str, entity_id: str) -> None:
    """Remove escalation tracking for a claimed/resolved item."""
    await session.execute(
        sa.text("DELETE FROM task_escalation_state WHERE entity_type = :entity_type AND entity_id = :entity_id"),
        {"entity_type": entity_type, "entity_id": entity_id},
    )


async def find_escalation_candidates(session, now: datetime) -> list[dict]:
    """Find unclaimed tasks/tickets past their escalation threshold."""
    result = await session.execute(
        sa.text(
            "SELECT entity_type, entity_id, current_priority, created_at, "
            "       escalated_at, escalation_count "
            "FROM task_escalation_state "
            "WHERE escalated_at IS NULL "
            "   OR (current_priority != 'critical' AND escalation_count < 3)"
        )
    )
    candidates = []
    for row in result.fetchall():
        priority = row._mapping["current_priority"]
        threshold = ESCALATION_THRESHOLDS.get(priority, 3600)
        check_time = row._mapping["escalated_at"] or row._mapping["created_at"]
        if (now - check_time).total_seconds() > threshold:
            candidates.append(dict(row._mapping))
    return candidates


async def check_and_escalate(session, publisher) -> int:
    """Check for escalation candidates and escalate them.

    Re-checks current status before firing to avoid escalating
    claimed/resolved items (ESC-06).

    Returns the number of items escalated.
    """
    now = datetime.now(tz=UTC)
    candidates = await find_escalation_candidates(session, now)

    escalated = 0
    for candidate in candidates:
        entity_type = candidate["entity_type"]
        entity_id = candidate["entity_id"]
        current_priority = candidate["current_priority"]
        created_at = candidate["created_at"]

        # Re-check current status (ESC-06)
        table = "tasks" if entity_type == "task" else "tickets"
        id_col = "task_id" if entity_type == "task" else "ticket_id"
        status_result = await session.execute(
            sa.text(f"SELECT status FROM {table} WHERE {id_col} = :entity_id"),
            {"entity_id": entity_id},
        )
        current_status = status_result.scalar_one_or_none()

        if current_status in _TERMINAL_STATUSES or current_status is None:
            await remove_escalation_state(session, entity_type, entity_id)
            log.info(
                "escalation_skipped_terminal",
                entity_type=entity_type,
                entity_id=entity_id,
                status=current_status,
            )
            continue

        # Determine new priority
        new_priority = PRIORITY_UPGRADE.get(current_priority, current_priority)
        new_count = candidate["escalation_count"] + 1

        # Update escalation state
        await session.execute(
            sa.text(
                "UPDATE task_escalation_state SET "
                "  current_priority = :new_priority, "
                "  escalated_at = :now, "
                "  last_checked_at = :now, "
                "  escalation_count = :new_count "
                "WHERE entity_type = :entity_type AND entity_id = :entity_id"
            ),
            {
                "new_priority": new_priority,
                "now": now,
                "new_count": new_count,
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )

        # Build and publish escalation event
        event_type = f"{entity_type}.escalated"
        topic = f"ocean.{entity_type}s"
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "schema_version": "1.0.0",
            "timestamp": now.isoformat(),
            "source_system": "control-plane",
            "entity_id": entity_id,
            "entity_type": entity_type,
            "correlation_id": "",
            "payload": {
                "old_priority": current_priority,
                "new_priority": new_priority,
                "escalation_count": new_count,
                "minutes_unclaimed": int((now - created_at).total_seconds() / 60),
                "policy_name": (f"auto_escalate_{current_priority}_{ESCALATION_THRESHOLDS[current_priority]}s"),
            },
        }
        await publisher.publish(topic, event)
        log.info(
            "task_escalated",
            entity_type=entity_type,
            entity_id=entity_id,
            old_priority=current_priority,
            new_priority=new_priority,
            escalation_count=new_count,
        )
        escalated += 1

    return escalated


async def rehydrate_and_catch_up(session, publisher) -> int:
    """On startup, escalate items that timed out during downtime.

    Returns the number of items escalated during catch-up.
    """
    return await check_and_escalate(session, publisher)


async def run_escalation_poller(session_maker, publisher, interval: int | None = None) -> None:
    """Background poller that periodically checks for escalation candidates.

    Disabled when ESCALATION_ENABLED is false (sim profile default).
    """
    if not ESCALATION_ENABLED:
        log.info("escalation_disabled")
        return

    interval = interval or POLL_INTERVAL
    log.info("escalation_poller_started", interval=interval)

    while True:
        try:
            async with session_maker() as session, session.begin():
                count = await check_and_escalate(session, publisher)
                if count:
                    log.info("escalation_poll_complete", escalated=count)
        except Exception:
            log.exception("escalation_poll_error")
        await asyncio.sleep(interval)
