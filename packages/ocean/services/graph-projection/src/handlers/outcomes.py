"""Graph projection handlers for call lifecycle and outcome.recorded events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

from src.handlers.sequence import event_time, sequence_guard

log = structlog.get_logger()

_OUTCOME_NS = uuid.NAMESPACE_URL


def _outcome_id(engagement_id: str, outcome_type: str) -> str:
    """Generate a deterministic outcome UUID from engagement_id + outcome_type."""
    return str(uuid.uuid5(_OUTCOME_NS, f"outcome-{engagement_id}-{outcome_type}"))


async def handle_call_completed(event_data: dict, session) -> None:
    """Project call.completed — upsert Interaction with outcome='completed' + insert Outcome.

    The interaction upsert is guarded on event time: a call.missed that was
    produced earlier but arrives later must not rewrite a completed call to
    missed. `completed_at` is processing time and is deliberately not the guard
    column — see `handlers/sequence.py`.
    """
    payload = event_data.get("payload", {})
    engagement_id = event_data.get("entity_id", "")
    task_id = payload.get("task_id") or ""
    patient_id = payload.get("patient_id", "")
    event_id = event_data.get("event_id", "")
    disposition = payload.get("disposition", "")
    event_at = event_time(event_data)
    now = datetime.now(tz=UTC)
    outcome_id = _outcome_id(engagement_id, "call_completed")

    # Upsert interaction — set outcome='completed', unless a newer event already wrote the row
    await session.execute(
        sa.text(
            "INSERT INTO interactions "
            "    (interaction_id, task_id, patient_id, interaction_type, outcome, "
            "     started_at, completed_at, last_event_at, last_event_id) "
            "VALUES "
            "    (:interaction_id, :task_id, :patient_id, 'call', 'completed', "
            "     :now, :now, :event_at, :event_id) "
            "ON CONFLICT (interaction_id) DO UPDATE SET "
            "    outcome = 'completed', "
            "    completed_at = EXCLUDED.completed_at, "
            "    last_event_at = EXCLUDED.last_event_at, "
            "    last_event_id = EXCLUDED.last_event_id " + sequence_guard("interactions")
        ),
        {
            "interaction_id": engagement_id,
            "task_id": task_id,
            "patient_id": patient_id,
            "now": now,
            "event_at": event_at,
            "event_id": event_id,
        },
    )

    # Insert outcome record — ON CONFLICT DO NOTHING for idempotency
    await session.execute(
        sa.text(
            "INSERT INTO outcomes "
            "    (outcome_id, interaction_id, patient_id, outcome_type, "
            "     resolution_status, notes, recorded_at, last_event_id) "
            "VALUES "
            "    (:outcome_id, :interaction_id, :patient_id, 'call_completed', "
            "     'resolved', :notes, :recorded_at, :event_id) "
            "ON CONFLICT (outcome_id) DO NOTHING"
        ),
        {
            "outcome_id": outcome_id,
            "interaction_id": engagement_id,
            "patient_id": patient_id,
            "notes": disposition,
            "recorded_at": now,
            "event_id": event_id,
        },
    )
    log.info("call_completed_projected", engagement_id=engagement_id, outcome_id=outcome_id)


async def handle_call_missed(event_data: dict, session) -> None:
    """Project call.missed — upsert Interaction with outcome='missed' + insert Outcome.

    Resolution status is 'no_contact' — no agent answered the call.

    Guarded on event time for the same reason as call.completed: this is the
    write that, unguarded, silently rewrote a completed call to missed.
    """
    payload = event_data.get("payload", {})
    engagement_id = event_data.get("entity_id", "")
    task_id = payload.get("task_id") or ""
    patient_id = payload.get("patient_id", "")
    event_id = event_data.get("event_id", "")
    event_at = event_time(event_data)
    now = datetime.now(tz=UTC)
    outcome_id = _outcome_id(engagement_id, "call_missed")

    # Upsert interaction — set outcome='missed', unless a newer event already wrote the row
    await session.execute(
        sa.text(
            "INSERT INTO interactions "
            "    (interaction_id, task_id, patient_id, interaction_type, outcome, "
            "     started_at, completed_at, last_event_at, last_event_id) "
            "VALUES "
            "    (:interaction_id, :task_id, :patient_id, 'call', 'missed', "
            "     :now, :now, :event_at, :event_id) "
            "ON CONFLICT (interaction_id) DO UPDATE SET "
            "    outcome = 'missed', "
            "    completed_at = EXCLUDED.completed_at, "
            "    last_event_at = EXCLUDED.last_event_at, "
            "    last_event_id = EXCLUDED.last_event_id " + sequence_guard("interactions")
        ),
        {
            "interaction_id": engagement_id,
            "task_id": task_id,
            "patient_id": patient_id,
            "now": now,
            "event_at": event_at,
            "event_id": event_id,
        },
    )

    # Insert outcome record — no_contact resolution
    await session.execute(
        sa.text(
            "INSERT INTO outcomes "
            "    (outcome_id, interaction_id, patient_id, outcome_type, "
            "     resolution_status, notes, recorded_at, last_event_id) "
            "VALUES "
            "    (:outcome_id, :interaction_id, :patient_id, 'call_missed', "
            "     'no_contact', NULL, :recorded_at, :event_id) "
            "ON CONFLICT (outcome_id) DO NOTHING"
        ),
        {
            "outcome_id": outcome_id,
            "interaction_id": engagement_id,
            "patient_id": patient_id,
            "recorded_at": now,
            "event_id": event_id,
        },
    )
    log.info("call_missed_projected", engagement_id=engagement_id)


async def handle_outcome_recorded(event_data: dict, session) -> None:
    """Project outcome.recorded — upsert outcomes table from normalized envelope.

    Uses the same _outcome_id pattern for deterministic IDs. interaction_id
    is NULL for task/ticket/alert outcomes (made nullable in migration 0014).
    """
    payload = event_data.get("payload", {})
    entity_type = payload.get("entity_type", "")
    entity_id = payload.get("entity_id", "")
    resolution_type = payload.get("resolution_type", "")
    event_id = event_data.get("event_id", "")
    now = datetime.now(tz=UTC)
    outcome_id = _outcome_id(entity_id, resolution_type)

    await session.execute(
        sa.text(
            "INSERT INTO outcomes "
            "    (outcome_id, interaction_id, patient_id, outcome_type, "
            "     resolution_status, notes, recorded_at, last_event_id) "
            "VALUES "
            "    (:outcome_id, NULL, '', :outcome_type, "
            "     :resolution_status, NULL, :recorded_at, :event_id) "
            "ON CONFLICT (outcome_id) DO NOTHING"
        ),
        {
            "outcome_id": outcome_id,
            "outcome_type": f"{entity_type}_{resolution_type}",
            "resolution_status": resolution_type,
            "recorded_at": now,
            "event_id": event_id,
        },
    )
    log.info(
        "outcome_recorded_projected",
        entity_type=entity_type,
        entity_id=entity_id,
        resolution_type=resolution_type,
        outcome_id=outcome_id,
    )
