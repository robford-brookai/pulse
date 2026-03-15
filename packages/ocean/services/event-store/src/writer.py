"""Async Postgres writer for Ocean events and audit log."""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = structlog.get_logger()

_engine = None
_AsyncSessionLocal = None


def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _engine, _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        database_url = os.environ["DATABASE_URL"]
        _engine = create_async_engine(database_url, echo=False)
        _AsyncSessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _AsyncSessionLocal


async def write_event(event_bytes: bytes, topic: str = "unknown") -> None:
    """Parse event bytes, write to events table, and append an audit_log row.

    Uses ON CONFLICT DO NOTHING for idempotency — duplicate event_id is silently ignored.
    Raises on all other errors so the caller can decide not to commit the Kafka offset.
    """
    event_data = json.loads(event_bytes)

    session_maker = _get_session_maker()
    async with session_maker() as session:
        async with session.begin():
            # Write to events table
            await session.execute(
                sa.text(
                    "INSERT INTO events "
                    "(event_id, event_type, schema_version, entity_type, entity_id, "
                    "source_system, correlation_id, actor_id, timestamp, payload) "
                    "VALUES "
                    "(:event_id, :event_type, :schema_version, :entity_type, :entity_id, "
                    ":source_system, :correlation_id, :actor_id, :timestamp, :payload) "
                    "ON CONFLICT (event_id) DO NOTHING"
                ),
                {
                    "event_id": event_data["event_id"],
                    "event_type": event_data["event_type"],
                    "schema_version": event_data.get("schema_version", "1.0.0"),
                    "entity_type": event_data.get("entity_type", "unknown"),
                    "entity_id": event_data.get("entity_id", "unknown"),
                    "source_system": event_data.get("source_system", "unknown"),
                    "correlation_id": event_data.get("correlation_id", ""),
                    "actor_id": event_data.get("actor_id"),
                    "timestamp": datetime.fromisoformat(
                        event_data.get("timestamp", "").replace("Z", "+00:00")
                    ),
                    "payload": json.dumps(event_data.get("payload", {})),
                },
            )

            # Append audit_log row — records that this event was ingested
            await session.execute(
                sa.text(
                    "INSERT INTO audit_log "
                    "(audit_id, event_id, action_type, actor_id, source_system, "
                    "entity_type, entity_id, timestamp, detail) "
                    "VALUES "
                    "(:audit_id, :event_id, :action_type, :actor_id, :source_system, "
                    ":entity_type, :entity_id, :timestamp, :detail)"
                ),
                {
                    "audit_id": str(uuid.uuid4()),
                    "event_id": event_data["event_id"],
                    "action_type": "event.ingested",
                    "actor_id": event_data.get("actor_id") or "system",
                    "source_system": event_data.get("source_system", "unknown"),
                    "entity_type": event_data.get("entity_type"),
                    "entity_id": event_data.get("entity_id"),
                    "timestamp": datetime.now(tz=UTC),
                    "detail": json.dumps(
                        {
                            "event_type": event_data.get("event_type"),
                            "topic": topic,
                        }
                    ),
                },
            )

    log.info("event_written", event_id=event_data["event_id"], topic=topic)
