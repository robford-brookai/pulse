"""Publisher wiring for call-simulator.

The service holds no transport code of its own. Addressing and the bus client live in
:mod:`ocean_broker`; this module names the domain call-simulator emits to and builds the shared
:class:`~ocean_broker.EventBridgePublisher`, giving it the Postgres session maker its
``failed_webhooks`` fallback needs.
"""

from __future__ import annotations

import os

from ocean_broker import EventBridgePublisher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

#: The one live OCEAN domain this service publishes to — the former ``ocean.interactions`` topic.
DOMAIN = "interactions"


def build_dlq_session_maker(database_url: str | None = None) -> async_sessionmaker[AsyncSession] | None:
    """Build the session maker backing the ``failed_webhooks`` fallback.

    Args:
        database_url: Postgres URL. Defaults to ``DATABASE_URL``.

    Returns:
        A session maker, or ``None`` when no URL is configured — the publisher then logs a failed
        publish rather than durably queueing it.
    """
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        return None
    engine = create_async_engine(database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def build_publisher(database_url: str | None = None) -> EventBridgePublisher:
    """Build the shared EventBridge publisher with call-simulator's DLQ fallback attached."""
    return EventBridgePublisher(db_session_maker=build_dlq_session_maker(database_url))
