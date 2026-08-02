"""Out-of-order delivery tests for the signals projection (DNA-741).

The signals upserts are exercised against a real SQL engine rather than a mock session: a
sequence guard lives entirely in the `ON CONFLICT ... DO UPDATE ... WHERE` clause, so a mock
that records the statement text proves nothing about whether the guard holds. SQLite is used
because the upsert grammar under test — `ON CONFLICT (col) DO UPDATE SET ... WHERE ...` with
`EXCLUDED` — is shared with Postgres, and the gate must run without Docker.

`received_at` is the guard column. It is event time: every handler derives it from the
envelope's `timestamp`, which is fixed when the event is produced, never at processing time.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
import sqlalchemy as sa
from src.handlers.signals import handle_signal_missing, handle_signal_received

# Ocean's asyncio_mode=auto applies only when pytest's rootdir is packages/ocean; the marker
# keeps these tests running when the suite is driven from the repo root.
pytestmark = pytest.mark.asyncio

SIGNALS_DDL = """
CREATE TABLE signals (
    signal_id     TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    signal_type   TEXT NOT NULL,
    value         REAL,
    unit          TEXT,
    received_at   TIMESTAMP NOT NULL,
    anomalous     BOOLEAN NOT NULL DEFAULT 0,
    last_event_id TEXT
)
"""


class _SyncSessionShim:
    """Adapts a synchronous SQLAlchemy connection to the `await session.execute(...)` surface."""

    def __init__(self, conn: sa.Connection) -> None:
        self._conn = conn

    async def execute(self, statement, params=None):
        return self._conn.execute(statement, params or {})


@pytest.fixture
def db():
    # sqlite3 dropped its implicit datetime adapter to a deprecation warning; the handlers bind
    # datetime objects through sa.text(), which carries no column type for the dialect to use.
    sqlite3.register_adapter(datetime, lambda dt: dt.isoformat(sep=" "))
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text(SIGNALS_DDL))
        yield conn
    engine.dispose()


def signal_state(conn: sa.Connection, signal_id: str = "s1") -> dict:
    row = conn.execute(
        sa.text("SELECT anomalous, last_event_id, received_at FROM signals WHERE signal_id = :sid"),
        {"sid": signal_id},
    ).one()
    return {"anomalous": bool(row.anomalous), "last_event_id": row.last_event_id, "received_at": row.received_at}


def received_event(event_id: str, timestamp: str, *, anomalous: bool = False, value: float = 5.0) -> dict:
    return {
        "event_id": event_id,
        "event_type": "signal.received",
        "entity_id": "s1",
        "timestamp": timestamp,
        "payload": {
            "patient_id": "p1",
            "signal_type": "glucose",
            "value": value,
            "unit": "mg/dL",
            "anomalous": anomalous,
        },
    }


def missing_event(event_id: str, timestamp: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "signal.missing",
        "entity_id": "s1",
        "timestamp": timestamp,
        "payload": {"patient_id": "p1", "signal_type": "glucose"},
    }


HANDLERS = {"signal.received": handle_signal_received, "signal.missing": handle_signal_missing}


async def project(conn: sa.Connection, events: list[dict]) -> dict:
    session = _SyncSessionShim(conn)
    for event in events:
        await HANDLERS[event["event_type"]](event, session)
    return signal_state(conn)


T1 = "2026-03-05T10:00:00Z"
T2 = "2026-03-05T11:00:00Z"
T3 = "2026-03-05T12:00:00Z"


async def test_stale_missing_does_not_flip_a_newer_signal_anomalous(db):
    """An older signal.missing arriving after a newer signal.received leaves the state unchanged."""
    await project(db, [received_event("evt-3", T3)])
    await project(db, [missing_event("evt-2", T2)])

    state = signal_state(db)
    assert state["anomalous"] is False
    assert state["last_event_id"] == "evt-3"


async def test_missing_still_applies_when_it_is_the_newer_event(db):
    """The guard drops stale writes only — a later signal.missing still marks the signal anomalous."""
    await project(db, [received_event("evt-1", T1), missing_event("evt-2", T2)])

    state = signal_state(db)
    assert state["anomalous"] is True
    assert state["last_event_id"] == "evt-2"


async def test_reverse_delivery_reaches_the_same_state_as_in_order(db):
    """Reverse-order delivery of one signal's lifecycle lands on the in-order final state."""
    events = [received_event("evt-1", T1), missing_event("evt-2", T2), received_event("evt-3", T3)]

    in_order = await project(db, events)

    db.execute(sa.text("DELETE FROM signals"))
    reversed_order = await project(db, list(reversed(events)))

    assert in_order == reversed_order
    assert in_order["anomalous"] is False
    assert in_order["last_event_id"] == "evt-3"


async def test_guard_advances_the_sequence_column_on_every_applied_write(db):
    """Each applied upsert moves `received_at` forward, so the guard compares against the newest event."""
    await project(db, [received_event("evt-1", T1), missing_event("evt-2", T2)])

    assert signal_state(db)["received_at"].startswith("2026-03-05 11:00:00")


async def test_guard_compares_event_time_not_processing_time(db):
    """Two events processed in sequence are ordered by their envelope timestamps, not arrival."""
    await project(db, [missing_event("evt-9", T3), received_event("evt-8", T1)])

    state = signal_state(db)
    assert state["anomalous"] is True
    assert state["last_event_id"] == "evt-9"
