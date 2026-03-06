"""Alert event handlers — stub. Implemented in 03-02."""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


async def handle_alert_created(event_data: dict, session: AsyncSession) -> None:
    """Handle alert.created events. Stub — implemented in 03-02."""
    log.debug("alert_created_stub", event_type=event_data.get("event_type"))


async def handle_alert_claimed(event_data: dict, session: AsyncSession) -> None:
    """Handle alert.claimed events. Stub — implemented in 03-02."""
    log.debug("alert_claimed_stub", event_type=event_data.get("event_type"))


async def handle_alert_resolved(event_data: dict, session: AsyncSession) -> None:
    """Handle alert.resolved events. Stub — implemented in 03-02."""
    log.debug("alert_resolved_stub", event_type=event_data.get("event_type"))
