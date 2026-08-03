"""Unit tests for graph-projection logistics event handlers."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fulfillment_event(
    order_id: str = "ORD-001",
    patient_id: str = "sha256_patient_abc",
    status: str = "shipped",
    shipping_option: str = "standard",
    tracking_numbers: list | None = None,
    order_items: list | None = None,
    devices: list | None = None,
) -> dict:
    return {
        "event_id": "evt-ful-001",
        "event_type": "fulfillment.updated",
        "entity_type": "fulfillment",
        "entity_id": order_id,
        "timestamp": "2026-03-13T10:00:00Z",
        "source_system": "impilo",
        "correlation_id": "corr-ful-001",
        "payload": {
            "order_id": order_id,
            "patient_id": patient_id,
            "status": status,
            "shipping_option": shipping_option,
            "tracking_numbers": tracking_numbers or ["1Z999AA10123456784"],
            "order_items": order_items or [{"sku": "BP-MONITOR", "qty": 1}],
            "devices": devices or [{"device_id": "dev-001", "name": "BP Monitor"}],
        },
    }


def _make_return_event(
    return_id: str = "RET-001",
    patient_id: str = "sha256_patient_abc",
    device_id: str = "dev-001",
    order_id: str = "ORD-001",
    status: str = "initiated",
    reason: str = "defective",
) -> dict:
    return {
        "event_id": "evt-ret-001",
        "event_type": "return.updated",
        "entity_type": "return",
        "entity_id": return_id,
        "timestamp": "2026-03-13T11:00:00Z",
        "source_system": "impilo",
        "correlation_id": "corr-ret-001",
        "payload": {
            "return_id": return_id,
            "patient_id": patient_id,
            "device_id": device_id,
            "order_id": order_id,
            "status": status,
            "reason": reason,
            "raw_payload": {"original": "impilo_data", "return_id": return_id},
        },
    }


def _make_device_associated_event(
    patient_id: str = "sha256_patient_abc",
    device_id: str = "dev-001",
    device_name: str = "BP Monitor",
    order_id: str = "ORD-001",
    event_id: str = "evt-da-001",
    timestamp: str = "2026-03-13T12:00:00Z",
) -> dict:
    return {
        "event_id": event_id,
        "event_type": "device.associated",
        "entity_type": "device_association",
        "entity_id": device_id,
        "timestamp": timestamp,
        "source_system": "impilo",
        "correlation_id": "corr-da-001",
        "payload": {
            "patient_id": patient_id,
            "device_id": device_id,
            "device_name": device_name,
            "order_id": order_id,
        },
    }


def _make_device_disassociated_event(
    patient_id: str = "sha256_patient_abc",
    device_id: str = "dev-001",
    device_name: str = "BP Monitor",
    event_id: str = "evt-dd-001",
    timestamp: str = "2026-03-13T13:00:00Z",
) -> dict:
    return {
        "event_id": event_id,
        "event_type": "device.disassociated",
        "entity_type": "device_association",
        "entity_id": device_id,
        "timestamp": timestamp,
        "source_system": "impilo",
        "correlation_id": "corr-dd-001",
        "payload": {
            "patient_id": patient_id,
            "device_id": device_id,
            "device_name": device_name,
        },
    }


@pytest.fixture
def mock_session():
    # rowcount=1 by default: the guarded upserts read it to tell an applied write
    # from one the sequence guard dropped.
    result = MagicMock()
    result.rowcount = 1
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# handle_fulfillment_updated
# ---------------------------------------------------------------------------


class TestHandleFulfillmentUpdated:
    @pytest.mark.asyncio
    async def test_inserts_fulfillment_with_correct_params(self, mock_session):
        """handle_fulfillment_updated upserts a fulfillments row with all fields."""
        from src.handlers.logistics import handle_fulfillment_updated

        event = _make_fulfillment_event()
        await handle_fulfillment_updated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "INSERT INTO fulfillments" in sql_text
        assert "ON CONFLICT" in sql_text
        assert params["order_id"] == "ORD-001"
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["status"] == "shipped"
        assert params["shipping_option"] == "standard"
        # JSONB fields should be serialized strings
        assert json.loads(params["tracking_numbers"]) == ["1Z999AA10123456784"]
        assert json.loads(params["order_items"]) == [{"sku": "BP-MONITOR", "qty": 1}]
        assert json.loads(params["devices"]) == [{"device_id": "dev-001", "name": "BP Monitor"}]

    @pytest.mark.asyncio
    async def test_idempotent_upsert_does_not_raise(self, mock_session):
        """Repeated fulfillment.updated calls for same order_id do not raise."""
        from src.handlers.logistics import handle_fulfillment_updated

        event = _make_fulfillment_event()
        await handle_fulfillment_updated(event, mock_session)
        await handle_fulfillment_updated(event, mock_session)
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_sql_has_updated_at_guard(self, mock_session):
        """ON CONFLICT clause includes WHERE updated_at < EXCLUDED.updated_at guard."""
        from src.handlers.logistics import handle_fulfillment_updated

        event = _make_fulfillment_event()
        await handle_fulfillment_updated(event, mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "WHERE fulfillments.updated_at < EXCLUDED.updated_at" in sql_text


# ---------------------------------------------------------------------------
# handle_return_updated
# ---------------------------------------------------------------------------


class TestHandleReturnUpdated:
    @pytest.mark.asyncio
    async def test_inserts_return_with_correct_params(self, mock_session):
        """handle_return_updated upserts a returns row with raw_payload."""
        from src.handlers.logistics import handle_return_updated

        event = _make_return_event()
        await handle_return_updated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "INSERT INTO returns" in sql_text
        assert "ON CONFLICT" in sql_text
        assert params["return_id"] == "RET-001"
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["device_id"] == "dev-001"
        assert params["status"] == "initiated"
        assert params["reason"] == "defective"
        # raw_payload should be serialized JSONB
        expected_raw = {"original": "impilo_data", "return_id": "RET-001"}
        assert json.loads(params["raw_payload"]) == expected_raw

    @pytest.mark.asyncio
    async def test_sql_has_updated_at_guard(self, mock_session):
        """ON CONFLICT clause includes WHERE guard."""
        from src.handlers.logistics import handle_return_updated

        event = _make_return_event()
        await handle_return_updated(event, mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "WHERE returns.updated_at < EXCLUDED.updated_at" in sql_text


# ---------------------------------------------------------------------------
# handle_device_associated
# ---------------------------------------------------------------------------


class TestHandleDeviceAssociated:
    @pytest.mark.asyncio
    async def test_inserts_device_association_active(self, mock_session):
        """handle_device_associated upserts with status='active'."""
        from src.handlers.logistics import handle_device_associated

        event = _make_device_associated_event()
        await handle_device_associated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "INSERT INTO device_associations" in sql_text
        assert "ON CONFLICT" in sql_text
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["device_id"] == "dev-001"
        assert params["device_name"] == "BP Monitor"

    @pytest.mark.asyncio
    async def test_reactivation_clears_removed_at(self, mock_session):
        """ON CONFLICT sets status='active' and removed_at=NULL."""
        from src.handlers.logistics import handle_device_associated

        event = _make_device_associated_event()
        await handle_device_associated(event, mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "status = 'active'" in sql_text
        assert "removed_at = NULL" in sql_text

    @pytest.mark.asyncio
    async def test_guard_compares_event_time_not_event_identity(self, mock_session):
        """The ON CONFLICT guard compares last_event_at, not last_event_id."""
        from src.handlers.logistics import handle_device_associated

        await handle_device_associated(_make_device_associated_event(), mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "last_event_at < EXCLUDED.last_event_at" in sql_text
        # Dedup is not ordering: the old identity predicate must be gone.
        assert "IS DISTINCT FROM" not in sql_text

    @pytest.mark.asyncio
    async def test_binds_envelope_timestamp_as_event_time(self, mock_session):
        """event_at is the envelope timestamp, fixed at production, not now()."""
        from src.handlers.logistics import handle_device_associated

        event = _make_device_associated_event(timestamp="2026-03-13T12:00:00Z")
        await handle_device_associated(event, mock_session)

        params = mock_session.execute.call_args[0][1]
        assert params["event_at"] == datetime.fromisoformat("2026-03-13T12:00:00+00:00")


# ---------------------------------------------------------------------------
# handle_device_disassociated
# ---------------------------------------------------------------------------


class TestHandleDeviceDisassociated:
    @pytest.mark.asyncio
    async def test_marks_device_removed(self, mock_session):
        """handle_device_disassociated records status='removed' and removed_at."""
        from src.handlers.logistics import handle_device_disassociated

        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_session.execute = AsyncMock(return_value=result_mock)

        event = _make_device_disassociated_event()
        await handle_device_disassociated(event, mock_session)

        assert mock_session.execute.called
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        params = call_args[0][1]

        assert "device_associations" in sql_text
        assert "status = 'removed'" in sql_text
        assert params["patient_id"] == "sha256_patient_abc"
        assert params["device_id"] == "dev-001"

    @pytest.mark.asyncio
    async def test_writes_a_tombstone_when_no_row_exists(self, mock_session):
        """A disassociation arriving first inserts the removed row rather than no-opping.

        Without the tombstone a later-arriving, older association would create an
        active row and the entity would converge to the wrong terminal state.
        """
        from src.handlers.logistics import handle_device_disassociated

        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_session.execute = AsyncMock(return_value=result_mock)

        await handle_device_disassociated(_make_device_disassociated_event(), mock_session)

        sql_text = str(mock_session.execute.call_args[0][0].text)
        assert "INSERT INTO device_associations" in sql_text
        assert "ON CONFLICT (patient_id, device_id) DO UPDATE SET" in sql_text

    @pytest.mark.asyncio
    async def test_guard_compares_event_time(self, mock_session):
        """The disassociation is guarded on last_event_at, not on status."""
        from src.handlers.logistics import handle_device_disassociated

        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_session.execute = AsyncMock(return_value=result_mock)

        event = _make_device_disassociated_event(timestamp="2026-03-13T13:00:00Z")
        await handle_device_disassociated(event, mock_session)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "last_event_at < EXCLUDED.last_event_at" in sql_text
        assert call_args[0][1]["event_at"] == datetime.fromisoformat("2026-03-13T13:00:00+00:00")

    @pytest.mark.asyncio
    async def test_stale_disassociation_does_not_raise(self, mock_session):
        """A guard-rejected write (rowcount 0) is logged, not raised."""
        from src.handlers.logistics import handle_device_disassociated

        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_session.execute = AsyncMock(return_value=result_mock)

        await handle_device_disassociated(_make_device_disassociated_event(), mock_session)
        assert mock_session.execute.called


# ---------------------------------------------------------------------------
# Out-of-order delivery — the handlers' real SQL against a real SQL engine
# ---------------------------------------------------------------------------

# SQLite speaks the same `ON CONFLICT (...) DO UPDATE SET ... WHERE ...` upsert and
# the same `:name` bind syntax the handlers emit, so the sequence guard is exercised
# by a SQL engine rather than by an assertion on a query string. Postgres-only types
# are widened to their SQLite equivalents; nothing in these two statements depends on
# them. This keeps the ordering test in the default run, with no Docker and no
# service dependency.
_DEVICE_ASSOCIATIONS_DDL = """
CREATE TABLE device_associations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    TEXT NOT NULL,
    device_id     TEXT NOT NULL,
    device_name   TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    associated_at TEXT NOT NULL,
    removed_at    TEXT,
    last_event_id TEXT,
    last_event_at TEXT,
    UNIQUE (patient_id, device_id)
)
"""


class _SqliteSession:
    """Async session double that runs the handlers' SQL against in-memory SQLite.

    A context manager because the connection it opens has to be closed. Left to the
    garbage collector it emits `ResourceWarning: unclosed database`, which pytest
    reports as a session-level `PytestUnraisableExceptionWarning` attributed to
    whichever test happened to be running when the collector fired — so the warning
    names an innocent test and the real culprit is invisible.
    """

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(_DEVICE_ASSOCIATIONS_DDL)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> _SqliteSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def execute(self, stmt, params):
        bound = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in params.items()}
        return self.conn.execute(str(stmt.text), bound)

    def state(self) -> list[dict]:
        """The projected state, minus the two processing-time columns.

        `associated_at` and `removed_at` are stamped with wall clock, so they differ
        between two runs by construction. `removed_at` still carries meaning as a
        presence flag, which is what is compared.
        """
        cur = self.conn.execute(
            "SELECT patient_id, device_id, device_name, status, removed_at, "
            "       last_event_id, last_event_at "
            "FROM device_associations ORDER BY patient_id, device_id"
        )
        rows = []
        for row in cur.fetchall():
            record = dict(row)
            record["removed_at"] = record["removed_at"] is not None
            rows.append(record)
        return rows


async def _deliver(events: list[dict]) -> list[dict]:
    from src.handlers.logistics import (
        handle_device_associated,
        handle_device_disassociated,
    )

    handlers = {
        "device.associated": handle_device_associated,
        "device.disassociated": handle_device_disassociated,
    }
    with _SqliteSession() as session:
        for event in events:
            await handlers[event["event_type"]](event, session)
        return session.state()


class TestDeviceAssociationOrdering:
    @pytest.mark.asyncio
    async def test_reverse_delivery_reaches_the_same_state(self):
        """Reverse-order delivery of a device lifecycle converges on in-order state."""
        lifecycle = [
            _make_device_associated_event(timestamp="2026-03-13T12:00:00Z"),
            _make_device_disassociated_event(timestamp="2026-03-13T13:00:00Z"),
        ]

        in_order = await _deliver(lifecycle)
        reversed_order = await _deliver(list(reversed(lifecycle)))

        assert in_order == reversed_order
        assert in_order[0]["status"] == "removed"
        assert in_order[0]["last_event_at"] == "2026-03-13T13:00:00+00:00"

    @pytest.mark.asyncio
    async def test_a_stale_association_does_not_resurrect_a_removed_device(self):
        """This is the bug the dedup-only predicate left open."""
        state = await _deliver([
            _make_device_disassociated_event(timestamp="2026-03-13T13:00:00Z"),
            _make_device_associated_event(timestamp="2026-03-13T12:00:00Z"),
        ])

        assert state[0]["status"] == "removed"
        assert state[0]["removed_at"] is True

    @pytest.mark.asyncio
    async def test_a_later_reassociation_is_applied(self):
        """The guard drops stale writes only — a genuinely newer event still lands."""
        state = await _deliver([
            _make_device_associated_event(timestamp="2026-03-13T12:00:00Z"),
            _make_device_disassociated_event(timestamp="2026-03-13T13:00:00Z"),
            _make_device_associated_event(
                device_name="BP Monitor v2",
                event_id="evt-da-002",
                timestamp="2026-03-13T14:00:00Z",
            ),
        ])

        assert state[0]["status"] == "active"
        assert state[0]["removed_at"] is False
        assert state[0]["device_name"] == "BP Monitor v2"

    @pytest.mark.asyncio
    async def test_reverse_delivery_of_two_associations_keeps_the_newer(self):
        updates = [
            _make_device_associated_event(
                device_name="BP Monitor", event_id="evt-da-001", timestamp="2026-03-13T12:00:00Z"
            ),
            _make_device_associated_event(
                device_name="BP Monitor v2", event_id="evt-da-002", timestamp="2026-03-13T14:00:00Z"
            ),
        ]

        assert await _deliver(updates) == await _deliver(list(reversed(updates)))
        assert (await _deliver(list(reversed(updates))))[0]["device_name"] == "BP Monitor v2"

    @pytest.mark.asyncio
    async def test_redelivery_of_the_same_event_is_a_no_op(self):
        """The guard subsumes the dedup the identity predicate used to provide."""
        event = _make_device_associated_event(timestamp="2026-03-13T12:00:00Z")

        once = await _deliver([event])
        twice = await _deliver([event, event])

        assert once == twice


# ---------------------------------------------------------------------------
# Consumer wiring
# ---------------------------------------------------------------------------


def test_logistics_events_registered_in_event_handlers():
    """All 4 logistics event types are registered in EVENT_HANDLERS."""
    from src.consumer import EVENT_HANDLERS

    assert "fulfillment.updated" in EVENT_HANDLERS
    assert "return.updated" in EVENT_HANDLERS
    assert "device.associated" in EVENT_HANDLERS
    assert "device.disassociated" in EVENT_HANDLERS


def test_logistics_event_types_registered():
    """Logistics event types stay registered after the SQS conversion (DNA-761).

    Topic subscription is retired; the logistics domain reaches this consumer
    via its dedicated EventBridge rule and queue.
    """
    from src.consumer import EVENT_HANDLERS

    for event_type in (
        "fulfillment.updated",
        "return.updated",
        "device.associated",
        "device.disassociated",
    ):
        assert event_type in EVENT_HANDLERS
