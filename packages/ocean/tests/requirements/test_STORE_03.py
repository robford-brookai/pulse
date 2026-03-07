"""STORE-03: Event store supports replay for projection rebuild.

Verification: Writing N events then replaying (writing same N events again) produces
no new rows thanks to ON CONFLICT DO NOTHING. This proves the event store is
idempotent to replay.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import sqlalchemy as sa

pytestmark = pytest.mark.integration

_ROOT = pathlib.Path(__file__).parents[2]
_EVENT_STORE = str(_ROOT / "services" / "event-store")


def _load_writer():
    spec = importlib.util.spec_from_file_location(
        "writer", os.path.join(_EVENT_STORE, "src", "writer.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def writer_mod(postgres_container, event_store_tables, session_factory):
    url = postgres_container.get_connection_url()
    async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    os.environ["DATABASE_URL"] = async_url
    mod = _load_writer()
    mod._engine = None
    mod._AsyncSessionLocal = None
    yield mod
    mod._engine = None
    mod._AsyncSessionLocal = None


@pytest_asyncio.fixture
async def clean_tables(session_factory, event_store_tables):
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                sa.text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete")
            )
            await session.execute(sa.text("DELETE FROM audit_log"))
            await session.execute(
                sa.text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete")
            )
            await session.execute(sa.text("DELETE FROM events"))
    yield


async def test_replay_idempotent(writer_mod, session_factory, clean_tables):
    """Write 10 events, replay same 10, verify row count unchanged."""
    event_ids = [str(uuid.uuid4()) for _ in range(10)]

    def _make_events():
        return [
            {
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
            for i, eid in enumerate(event_ids)
        ]

    # First pass
    for event in _make_events():
        await writer_mod.write_event(json.dumps(event).encode(), topic="ocean.signals")

    async with session_factory() as session:
        result = await session.execute(sa.text("SELECT COUNT(*) FROM events"))
        count = result.scalar()
    assert count == 10, f"Expected 10 events after first write, got {count}"

    # Replay -- same event_ids
    for event in _make_events():
        await writer_mod.write_event(json.dumps(event).encode(), topic="ocean.signals")

    async with session_factory() as session:
        result = await session.execute(sa.text("SELECT COUNT(*) FROM events"))
        count = result.scalar()
    assert count == 10, f"Expected still 10 events after replay, got {count}"
