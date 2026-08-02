"""Graph projection handlers for call lifecycle — started and connected events."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()

# Sequence guard shared by both call-lifecycle upserts. `last_event_at` is the envelope's
# produced-at timestamp, so the newest event by event time wins whatever order delivery
# happens in. Comparing `last_event_id` instead — the predicate this replaced — only
# suppressed a repeat of the same event; a distinct, earlier event still overwrote a newer
# one. `IS NULL` covers rows written before the column existed, which would otherwise be
# frozen forever. Equal timestamps do not update, so exact duplicates remain a no-op.
_SEQUENCE_GUARD = "WHERE interactions.last_event_at IS NULL OR interactions.last_event_at < EXCLUDED.last_event_at"

_UPSERT_INTERACTION = (
    "INSERT INTO interactions "
    "    (interaction_id, task_id, patient_id, interaction_type, outcome, "
    "     started_at, completed_at, last_event_id, last_event_at) "
    "VALUES "
    "    (:interaction_id, :task_id, :patient_id, 'call', NULL, "
    "     :event_at, NULL, :event_id, :event_at) "
    "ON CONFLICT (interaction_id) DO UPDATE SET "
    "    started_at = EXCLUDED.started_at, "
    "    last_event_id = EXCLUDED.last_event_id, "
    "    last_event_at = EXCLUDED.last_event_at "
) + _SEQUENCE_GUARD


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _upsert_params(event_data: dict) -> dict:
    payload = event_data.get("payload", {})
    return {
        "interaction_id": event_data.get("entity_id", ""),
        "task_id": payload.get("task_id") or "",
        "patient_id": payload.get("patient_id", ""),
        "event_id": event_data.get("event_id", ""),
        # Event time, not processing time. `started_at` is written from it too: under
        # reordering a `now()` value would encode arrival order, so the same events
        # delivered in a different order would leave a different row.
        "event_at": _parse_ts(event_data["timestamp"]),
    }


async def handle_call_started(event_data: dict, session) -> None:
    """Project call.started — INSERT interaction with interaction_type='call'.

    Uses INSERT ON CONFLICT DO UPDATE with an event-time sequence guard, so a late-arriving
    older event cannot overwrite state a newer one already wrote.
    """
    params = _upsert_params(event_data)
    await session.execute(sa.text(_UPSERT_INTERACTION), params)
    log.info("call_started_projected", engagement_id=params["interaction_id"])


async def handle_call_connected(event_data: dict, session) -> None:
    """Project call.connected — upsert interaction with updated started_at (answered time).

    No outcome set — call is in progress. Same event-time sequence guard as call.started.
    """
    params = _upsert_params(event_data)
    await session.execute(sa.text(_UPSERT_INTERACTION), params)
    log.info("call_connected_projected", engagement_id=params["interaction_id"])
