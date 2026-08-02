"""AUDIT-02: Audit log entries cannot be modified or deleted.

Verification: The audit_log_immutable trigger (from migration 0001) raises an
exception on UPDATE and DELETE, enforcing HIPAA append-only compliance per
45 C.F.R. 164.312(b).
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


@pytest.fixture
async def audit_row(event_store_tables, session_factory):
    """Insert a single audit_log row for testing mutations against."""
    audit_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                sa.text(
                    "INSERT INTO audit_log "
                    "(audit_id, event_id, action_type, actor_id, source_system, "
                    "entity_type, entity_id, timestamp, detail) VALUES "
                    "(:audit_id, :event_id, 'event.ingested', 'test', 'test', "
                    "'test', 'test-001', now(), '{}')"
                ),
                {"audit_id": audit_id, "event_id": event_id},
            )
    return audit_id


async def test_audit_log_rejects_update(audit_row, session_factory):
    """UPDATE on audit_log must raise with 'append-only' in the error message."""
    with pytest.raises(DBAPIError, match="append-only"):
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    sa.text(
                        "UPDATE audit_log SET action_type = 'tampered' "
                        "WHERE audit_id = :aid"
                    ),
                    {"aid": audit_row},
                )


async def test_audit_log_rejects_delete(audit_row, session_factory):
    """DELETE on audit_log must raise with 'append-only' in the error message."""
    with pytest.raises(DBAPIError, match="append-only"):
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    sa.text("DELETE FROM audit_log WHERE audit_id = :aid"),
                    {"aid": audit_row},
                )
