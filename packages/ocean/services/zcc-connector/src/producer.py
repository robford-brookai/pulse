"""Publisher wiring for the ZCC connector.

The connector holds no transport code of its own. Publishing is
:class:`ocean_broker.EventBridgePublisher`, which resolves its bus addressing from the event
catalog; this module only supplies the Postgres session maker that publisher's
``failed_webhooks`` fallback writes through.
"""

from __future__ import annotations

import os

from ocean_broker import EventBridgePublisher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def build_dlq_session_maker() -> async_sessionmaker[AsyncSession]:
    """Build the session maker the publisher's ``failed_webhooks`` fallback writes through."""
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def build_publisher(db_session_maker: async_sessionmaker[AsyncSession] | None = None) -> EventBridgePublisher:
    """Build the connector's publisher.

    Args:
        db_session_maker: Session maker for the ``failed_webhooks`` fallback. Built from
            ``DATABASE_URL`` when omitted. The fallback is not optional — a missing
            ``DATABASE_URL`` raises at startup rather than leaving failed publishes to be
            logged and dropped.
    """
    return EventBridgePublisher(db_session_maker=db_session_maker or build_dlq_session_maker())
