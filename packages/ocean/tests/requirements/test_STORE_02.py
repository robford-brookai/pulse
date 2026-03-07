"""STORE-02: Postgres event store is append-only ledger.

Verification: Writing N events via writer.write_event() results in exactly N rows.
The events table is append-only by convention (application code only inserts, never
deletes). Unlike audit_log, events has no DB-level trigger preventing DELETE -- the
append-only guarantee is enforced at the application layer.
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


def _make_event(index: int = 0) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "test.created",
        "schema_version": "1.0.0",
        "entity_type": "test",
        "entity_id": f"test-{index:03d}",
        "source_system": "test",
        "correlation_id": "",
        "actor_id": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {},
    }


async def test_append_only_5_events(writer_mod, session_factory, clean_tables):
    """Write 5 events via writer.write_event(), verify 5 rows in events table."""
    for i in range(5):
        await writer_mod.write_event(
            json.dumps(_make_event(index=i)).encode(), topic="ocean.signals"
        )

    async with session_factory() as session:
        result = await session.execute(sa.text("SELECT COUNT(*) FROM events"))
        count = result.scalar()
    assert count == 5, f"Expected 5 events, got {count}"


def test_append_only_by_convention_no_delete_in_writer():
    """writer module exposes only write_event -- no delete or update functions.

    The append-only guarantee for events is enforced by convention: the application
    code (writer.py) only provides INSERT. There is no delete_event or update_event.
    """
    import inspect

    mod = _load_writer()
    public_funcs = [
        name for name, obj in inspect.getmembers(mod)
        if callable(obj) and not name.startswith("_")
    ]
    assert "write_event" in public_funcs
    assert "delete_event" not in public_funcs
    assert "update_event" not in public_funcs
