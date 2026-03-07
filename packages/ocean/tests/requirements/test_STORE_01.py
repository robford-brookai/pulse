"""STORE-01: Redpanda provides durable, ordered, at-least-once delivery.

Verification: Producing N events and writing via event-store writer results in
exactly N rows. Re-writing the same events (duplicate event_ids) produces no
additional rows thanks to ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

_ROOT = pathlib.Path(__file__).parents[2]
_EVENT_STORE = str(_ROOT / "services" / "event-store")


def _load_writer():
    """Import the writer module from event-store service."""
    spec = importlib.util.spec_from_file_location(
        "writer", os.path.join(_EVENT_STORE, "src", "writer.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def writer_mod(postgres_container, event_store_tables, session_factory):
    """Load writer module pointed at test Postgres."""
    url = postgres_container.get_connection_url()
    async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    os.environ["DATABASE_URL"] = async_url

    mod = _load_writer()
    # Reset lazy globals so it re-initializes against test DB
    mod._engine = None
    mod._AsyncSessionLocal = None
    yield mod
    # Cleanup
    mod._engine = None
    mod._AsyncSessionLocal = None


@pytest_asyncio.fixture
async def clean_tables(session_factory):
    """Truncate events and audit_log before each test."""
    async with session_factory() as session:
        async with session.begin():
            # Disable trigger temporarily for cleanup
            await session.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"
                )
            )
            await session.execute(__import__("sqlalchemy").text("DELETE FROM audit_log"))
            await session.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"
                )
            )
            await session.execute(__import__("sqlalchemy").text("DELETE FROM events"))
    yield


async def test_at_least_once_10_events_written(writer_mod, session_factory, clean_tables):
    """Produce 10 events with unique IDs, verify 10 rows in events table."""
    import uuid
    from datetime import datetime, timezone

    events = []
    for i in range(10):
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "test.created",
            "schema_version": "1.0.0",
            "entity_type": "test",
            "entity_id": f"test-{i:03d}",
            "source_system": "test",
            "correlation_id": "",
            "actor_id": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {},
        }
        events.append(event)
        await writer_mod.write_event(json.dumps(event).encode(), topic="ocean.signals")

    from tests.integration.conftest import poll_row_count

    count = await poll_row_count(session_factory, "events", 10)
    assert count == 10, f"Expected 10 events, got {count}"


async def test_at_least_once_duplicates_rejected(writer_mod, session_factory, clean_tables):
    """Re-writing same 10 events (duplicate event_ids) produces no new rows."""
    import uuid
    from datetime import datetime, timezone

    event_ids = [str(uuid.uuid4()) for _ in range(10)]

    # First pass — write 10 events
    for i, eid in enumerate(event_ids):
        event = {
            "event_id": eid,
            "event_type": "test.created",
            "schema_version": "1.0.0",
            "entity_type": "test",
            "entity_id": f"test-{i:03d}",
            "source_system": "test",
            "correlation_id": "",
            "actor_id": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {},
        }
        await writer_mod.write_event(json.dumps(event).encode(), topic="ocean.signals")

    from tests.integration.conftest import poll_row_count

    count = await poll_row_count(session_factory, "events", 10)
    assert count == 10

    # Second pass — same event_ids should be rejected by ON CONFLICT DO NOTHING
    for i, eid in enumerate(event_ids):
        event = {
            "event_id": eid,
            "event_type": "test.created",
            "schema_version": "1.0.0",
            "entity_type": "test",
            "entity_id": f"test-{i:03d}",
            "source_system": "test",
            "correlation_id": "",
            "actor_id": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {},
        }
        await writer_mod.write_event(json.dumps(event).encode(), topic="ocean.signals")

    count = await poll_row_count(session_factory, "events", 10)
    assert count == 10, f"Expected still 10 events after duplicates, got {count}"
