"""Graph projection handlers for operational events (ocean.ops topic)."""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_connector_heartbeat(event_data: dict, session) -> None:
    """Project connector.heartbeat — upsert connector_health with last_seen."""
    payload = event_data.get("payload", {})
    connector_id = (
        payload.get("connector_id") or event_data.get("source_system", "unknown")
    )
    connector_name = payload.get("connector_name", connector_id)
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO connector_health "
            "  (connector_id, connector_name, last_seen, created_at) "
            "VALUES (:connector_id, :connector_name, :last_seen, :created_at) "
            "ON CONFLICT (connector_id) DO UPDATE SET "
            "  connector_name = EXCLUDED.connector_name, "
            "  last_seen = EXCLUDED.last_seen "
            "WHERE connector_health.last_seen < EXCLUDED.last_seen"
        ),
        {
            "connector_id": connector_id,
            "connector_name": connector_name,
            "last_seen": now,
            "created_at": now,
        },
    )
    log.debug("connector_health_projected", connector_id=connector_id)


async def handle_scenario_completed(event_data: dict, session) -> None:
    """Project scenario.completed — upsert simulations with run stats."""
    payload = event_data.get("payload", {})
    scenario_name = payload.get("scenario_name", event_data.get("entity_id", ""))
    ts = _parse_ts(event_data["timestamp"])

    await session.execute(
        sa.text(
            "INSERT INTO simulations "
            "  (scenario_name, completed_at, patients_count, alerts_generated, "
            "   tasks_created, duration_seconds, last_event_id) "
            "VALUES "
            "  (:scenario_name, :completed_at, :patients_count, "
            "   :alerts_generated, :tasks_created, :duration_seconds, "
            "   :event_id) "
            "ON CONFLICT (scenario_name) DO UPDATE SET "
            "  completed_at = EXCLUDED.completed_at, "
            "  patients_count = EXCLUDED.patients_count, "
            "  alerts_generated = EXCLUDED.alerts_generated, "
            "  tasks_created = EXCLUDED.tasks_created, "
            "  duration_seconds = EXCLUDED.duration_seconds, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE simulations.completed_at < EXCLUDED.completed_at"
        ),
        {
            "scenario_name": scenario_name,
            "completed_at": ts,
            "patients_count": payload.get("patients_count", 0),
            "alerts_generated": payload.get("alerts_generated", 0),
            "tasks_created": payload.get("tasks_created", 0),
            "duration_seconds": payload.get("duration_seconds", 0.0),
            "event_id": event_data.get("event_id", ""),
        },
    )
    log.info("simulation_projected", scenario_name=scenario_name)
