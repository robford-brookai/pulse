"""Connector heartbeat handlers — stub. Implemented in 03-02."""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


async def handle_connector_heartbeat(event_data: dict, session: AsyncSession) -> None:
    """Handle connector.heartbeat events from ocean.ops. Stub — implemented in 03-02."""
    log.debug("connector_heartbeat_stub", event_type=event_data.get("event_type"))
