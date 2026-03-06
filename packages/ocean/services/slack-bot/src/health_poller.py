"""Connector health poller — stub. Implemented in 03-02."""
from __future__ import annotations

import structlog

log = structlog.get_logger()


async def poll_connector_health() -> None:
    """Poll connector_health table and emit alerts for stale connectors.

    Stub — implemented in 03-02.
    """
    return
