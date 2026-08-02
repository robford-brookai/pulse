"""Control plane handler for connector.heartbeat events."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


async def handle_connector_heartbeat(event_data: dict, session, producer=None) -> None:
    """Handle connector.heartbeat events: upsert connector_health with last_seen timestamp."""
    payload = event_data.get("payload", {})
    # Prefer explicit connector_id in payload; fall back to source_system
    connector_id = payload.get("connector_id") or event_data.get("source_system", "unknown")
    connector_name = payload.get("connector_name", connector_id)
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO connector_health (connector_id, connector_name, last_seen, created_at) "
            "VALUES (:connector_id, :connector_name, :last_seen, :created_at) "
            "ON CONFLICT (connector_id) DO UPDATE SET "
            "  connector_name = EXCLUDED.connector_name, "
            "  last_seen = EXCLUDED.last_seen"
        ),
        {
            "connector_id": connector_id,
            "connector_name": connector_name,
            "last_seen": now,
            "created_at": now,
        },
    )
    log.debug("heartbeat_recorded", connector_id=connector_id)
