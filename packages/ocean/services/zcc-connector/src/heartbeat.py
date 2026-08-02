"""Heartbeat background task for the ZCC connector.

Publishes periodic connector.heartbeat events to the ops domain so the
control-plane can update connector_health and the slack-bot health
poller can detect silent connectors.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import structlog

log = structlog.get_logger()

HEARTBEAT_INTERVAL_SECS = 60  # Must be < 300s silence threshold


async def publish_heartbeat(
    publisher,
    connector_id: str,
    connector_name: str,
) -> None:
    """Infinite loop that publishes heartbeat events at a fixed interval.

    CancelledError from asyncio.sleep propagates out for clean shutdown.
    Publisher exceptions are caught and logged without crashing.
    """
    while True:
        event = {
            "event_id": str(uuid4()),
            "event_type": "connector.heartbeat",
            "schema_version": "1.0.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "source_system": connector_id,
            "entity_type": "connector",
            "entity_id": connector_id,
            "correlation_id": str(uuid4()),
            "actor_id": None,
            "payload": {
                "connector_id": connector_id,
                "connector_name": connector_name,
            },
        }
        try:
            await publisher.publish(
                detail_type="ops",
                event=event,
                key=connector_id,
            )
            log.debug("heartbeat_published", connector_id=connector_id)
        except Exception:
            log.exception("heartbeat_publish_failed", connector_id=connector_id)

        await asyncio.sleep(HEARTBEAT_INTERVAL_SECS)
