"""Graph projection handlers for call lifecycle — started and connected events."""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


async def handle_call_started(event_data: dict, session) -> None:
    """Project call.started — INSERT interaction with interaction_type='call'.

    Uses INSERT ON CONFLICT DO UPDATE so late-arriving or duplicate events
    do not corrupt state — idempotent via last_event_id guard.
    """
    payload = event_data.get("payload", {})
    engagement_id = event_data.get("entity_id", "")
    task_id = payload.get("task_id") or ""
    patient_id = payload.get("patient_id", "")
    event_id = event_data.get("event_id", "")
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO interactions "
            "    (interaction_id, task_id, patient_id, interaction_type, outcome, "
            "     started_at, completed_at, last_event_id) "
            "VALUES "
            "    (:interaction_id, :task_id, :patient_id, 'call', NULL, "
            "     :started_at, NULL, :event_id) "
            "ON CONFLICT (interaction_id) DO UPDATE SET "
            "    started_at = EXCLUDED.started_at, "
            "    last_event_id = EXCLUDED.last_event_id "
            "WHERE interactions.last_event_id IS DISTINCT FROM EXCLUDED.last_event_id"
        ),
        {
            "interaction_id": engagement_id,
            "task_id": task_id,
            "patient_id": patient_id,
            "started_at": now,
            "event_id": event_id,
        },
    )
    log.info("call_started_projected", engagement_id=engagement_id)


async def handle_call_connected(event_data: dict, session) -> None:
    """Project call.connected — upsert interaction with updated started_at (answered time).

    No outcome set — call is in progress.
    """
    payload = event_data.get("payload", {})
    engagement_id = event_data.get("entity_id", "")
    task_id = payload.get("task_id") or ""
    patient_id = payload.get("patient_id", "")
    event_id = event_data.get("event_id", "")
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO interactions "
            "    (interaction_id, task_id, patient_id, interaction_type, outcome, "
            "     started_at, completed_at, last_event_id) "
            "VALUES "
            "    (:interaction_id, :task_id, :patient_id, 'call', NULL, "
            "     :started_at, NULL, :event_id) "
            "ON CONFLICT (interaction_id) DO UPDATE SET "
            "    started_at = EXCLUDED.started_at, "
            "    last_event_id = EXCLUDED.last_event_id "
            "WHERE interactions.last_event_id IS DISTINCT FROM EXCLUDED.last_event_id"
        ),
        {
            "interaction_id": engagement_id,
            "task_id": task_id,
            "patient_id": patient_id,
            "started_at": now,
            "event_id": event_id,
        },
    )
    log.info("call_connected_projected", engagement_id=engagement_id)
