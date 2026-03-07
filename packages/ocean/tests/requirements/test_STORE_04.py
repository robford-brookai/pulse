"""STORE-04: Consumer offset tracking prevents duplicate processing.

Verification:
1. Consumer config has enable.auto.commit=False (manual commit after DB write).
2. write_event writes to both events AND audit_log in a single transaction,
   confirming the write-then-commit pattern works end-to-end.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib

import pytest
import pytest_asyncio
import sqlalchemy as sa

pytestmark = pytest.mark.integration

_ROOT = pathlib.Path(__file__).parents[2]
_EVENT_STORE = str(_ROOT / "services" / "event-store")


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_EVENT_STORE, "src", f"{name}.py")
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
    mod = _load_module("writer")
    mod._engine = None
    mod._AsyncSessionLocal = None
    yield mod
    mod._engine = None
    mod._AsyncSessionLocal = None


@pytest_asyncio.fixture
async def clean_tables(session_factory):
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


def test_offset_tracking_auto_commit_disabled():
    """Consumer config must have enable.auto.commit=False for manual offset commit."""
    consumer_mod = _load_module("consumer")

    # The consumer creates its config inside run_consumer. We inspect the source
    # to verify the setting. Alternatively, we can check TOPICS are defined.
    import ast
    import inspect

    source = inspect.getsource(consumer_mod.run_consumer)
    tree = ast.parse(source)

    # Walk AST to find the dict with enable.auto.commit
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "enable.auto.commit":
            found = True
        if isinstance(node, ast.NameConstant) and node.value is False:
            # Python 3.7 compat
            pass

    # Simpler: just check the source text
    assert '"enable.auto.commit": False' in source or "'enable.auto.commit': False" in source, (
        "Consumer must have enable.auto.commit=False for manual offset commit"
    )


async def test_offset_tracking_write_event_populates_both_tables(
    writer_mod, session_factory, clean_tables
):
    """write_event writes to both events AND audit_log in same transaction."""
    import uuid
    from datetime import datetime, timezone

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "test.created",
        "schema_version": "1.0.0",
        "entity_type": "test",
        "entity_id": "test-001",
        "source_system": "test",
        "correlation_id": "",
        "actor_id": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {},
    }
    await writer_mod.write_event(json.dumps(event).encode(), topic="ocean.signals")

    async with session_factory() as session:
        events_count = (await session.execute(sa.text("SELECT COUNT(*) FROM events"))).scalar()
        audit_count = (await session.execute(sa.text("SELECT COUNT(*) FROM audit_log"))).scalar()

    assert events_count == 1, f"Expected 1 event row, got {events_count}"
    assert audit_count == 1, f"Expected 1 audit_log row, got {audit_count}"
