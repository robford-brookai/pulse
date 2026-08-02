"""EventBridge publisher wiring for sim-driver synthetic events.

sim-driver holds no transport code of its own: it builds the shared
:class:`ocean_broker.publisher.EventBridgePublisher` and hands it to the scenario engine.
Addressing comes from the event catalog, so the domains below are catalog names
(``signals``), never the retired ``ocean.<domain>`` topic strings.
"""

from __future__ import annotations

import os

from ocean_broker.publisher import EventBridgePublisher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

#: The three domains sim-driver publishes to. Named here so a typo is one broken import
#: rather than a KeyError raised at the first publish of a scenario run.
DOMAIN_SIGNALS = "signals"
DOMAIN_ALERTS = "alerts"
DOMAIN_OPS = "ops"


def build_publisher(database_url: str | None = None) -> EventBridgePublisher:
    """Build the EventBridge publisher for this service.

    Args:
        database_url: Async Postgres URL backing the ``failed_webhooks`` dead-letter table.
            Defaults to ``DATABASE_URL``. sim-driver ships without a database, in which case
            a failed publish is logged and dropped — the same events are reproducible by
            re-running the scenario, so there is nothing to recover.

    Returns:
        The shared publisher, with the DLQ fallback wired when a database is configured.
    """
    database_url = database_url or os.environ.get("DATABASE_URL")
    session_maker = _build_session_maker(database_url) if database_url else None
    return EventBridgePublisher(db_session_maker=session_maker)


def _build_session_maker(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Build an async session maker for the dead-letter table."""
    engine = create_async_engine(database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
