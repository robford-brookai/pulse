"""Publisher wiring for agent-worker.

The transport is ocean-broker's :class:`EventBridgePublisher`; this module only resolves what the
service knows and the library does not — the Postgres connection behind the ``failed_webhooks``
dead-letter fallback. Nothing here addresses the bus: the domain → ``(source, detail-type)`` mapping
lives in the shared event catalog.
"""

from __future__ import annotations

import os

import structlog
from ocean_broker import EventBridgePublisher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = structlog.get_logger()


def build_publisher() -> EventBridgePublisher:
    """Build the shared EventBridge publisher for this service.

    Under Kafka this service published fire-and-forget with no dead-letter path. It gains one here
    by inheritance: a bus failure writes the envelope to ``failed_webhooks`` instead of dropping it,
    provided ``DATABASE_URL`` points at the Postgres holding that table.
    """
    return EventBridgePublisher(db_session_maker=_dlq_session_maker())


def _dlq_session_maker() -> async_sessionmaker[AsyncSession] | None:
    """Return the session maker for the dead-letter table, or None if no database is configured.

    A missing ``DATABASE_URL`` is logged rather than raised: without it the service still publishes,
    it just cannot durably queue a failed envelope, and the publisher already logs that case per
    event.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.warning("dlq_not_configured", reason="DATABASE_URL is unset; failed publishes are logged only")
        return None
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)
