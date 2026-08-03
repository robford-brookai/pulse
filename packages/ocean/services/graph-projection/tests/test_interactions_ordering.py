"""Ordering tests for the interaction upserts — event-time sequence guard (DNA-739).

`handle_call_started` and `handle_call_connected` were guarded by
`last_event_id IS DISTINCT FROM EXCLUDED.last_event_id`. That predicate suppresses a
*repeat of the same event*; it does nothing about a *different, earlier* event arriving
after a newer one. Under unordered delivery the older event won.

These tests pin the replacement: a guard comparing `last_event_at`, an event-time column
fed from the envelope's `timestamp`, so the newest event by event time wins regardless of
arrival order.

The ordering tests execute the handlers' real SQL against an in-memory SQLite database via
a minimal session shim. SQLite implements `INSERT ... ON CONFLICT DO UPDATE ... WHERE` with
the same semantics Postgres does for this statement, so the guard predicate is exercised
rather than string-matched. No Docker, no new dependency.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest

# SQLite has no native datetime type. Store timestamps as normalized UTC ISO-8601 text,
# which orders lexicographically exactly as the instants order.
sqlite3.register_adapter(datetime, lambda d: d.astimezone(UTC).isoformat())

_CREATE_INTERACTIONS = """
CREATE TABLE interactions (
    interaction_id   TEXT PRIMARY KEY,
    task_id          TEXT,
    patient_id       TEXT,
    interaction_type TEXT,
    outcome          TEXT,
    started_at       TEXT,
    completed_at     TEXT,
    last_event_id    TEXT,
    last_event_at    TEXT
)
"""


class _SqliteSession:
    """Just enough of an async SQLAlchemy session to run a `sa.text()` clause on SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.statements: list[str] = []

    async def execute(self, clause, params=None):
        self.statements.append(clause.text)
        self._conn.execute(clause.text, params or {})


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute(_CREATE_INTERACTIONS)
    yield conn
    conn.close()


def _row(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM interactions WHERE interaction_id = 'eng-1'")
    return dict(cur.fetchone())


def _event(event_type: str, event_id: str, timestamp: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "source_system": "zcc",
        "entity_id": "eng-1",
        "entity_type": "interaction",
        "actor_id": "agent-1",
        "timestamp": timestamp,
        "payload": {"patient_id": "pt-001", "task_id": "task-1"},
    }


STARTED = _event("call.started", "evt-started", "2026-03-05T10:00:00Z")
CONNECTED = _event("call.connected", "evt-connected", "2026-03-05T10:00:30Z")


async def _deliver(session, event: dict) -> None:
    from src.handlers.interactions import handle_call_connected, handle_call_started

    handler = {"call.started": handle_call_started, "call.connected": handle_call_connected}[event["event_type"]]
    await handler(event, session)


# ---------------------------------------------------------------------------
# The guard predicate itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("handler_name", ["handle_call_started", "handle_call_connected"])
@pytest.mark.asyncio
async def test_guard_compares_event_time_not_the_event_id(handler_name, db):
    """The dedup-only predicate is gone; the guard compares the event-time column."""
    import src.handlers.interactions as mod

    session = _SqliteSession(db)
    await getattr(mod, handler_name)(STARTED, session)

    sql = " ".join(session.statements[0].split())
    assert "IS DISTINCT FROM" not in sql, "dedup-only predicate must not survive"
    assert "interactions.last_event_at < EXCLUDED.last_event_at" in sql
    assert "interactions.last_event_at IS NULL" in sql, "pre-existing NULL rows must still update"


@pytest.mark.parametrize("handler_name", ["handle_call_started", "handle_call_connected"])
@pytest.mark.asyncio
async def test_event_time_comes_from_the_envelope_not_the_clock(handler_name, db):
    """`last_event_at` is the produced-at timestamp — a processing-time guard is a review-reject."""
    import src.handlers.interactions as mod

    session = _SqliteSession(db)
    await getattr(mod, handler_name)(STARTED, session)

    assert _row(db)["last_event_at"] == "2026-03-05T10:00:00+00:00"


@pytest.mark.parametrize("handler_name", ["handle_call_started", "handle_call_connected"])
@pytest.mark.asyncio
async def test_started_at_is_event_time(handler_name, db):
    """`started_at` must be deterministic too, or reordering changes the stored value."""
    import src.handlers.interactions as mod

    session = _SqliteSession(db)
    await getattr(mod, handler_name)(STARTED, session)

    assert _row(db)["started_at"] == "2026-03-05T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Delivery-order scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_delivery_reaches_the_same_state_as_in_order(db):
    """event-delivery: reverse-order delivery yields state identical to in-order delivery."""
    # closing() rather than a bare close() below: if a handler or assertion raises, the
    # connection still has to go, or the leak reappears only on the failure path — the
    # hardest version of this bug to see.
    with closing(sqlite3.connect(":memory:")) as in_order:
        in_order.execute(_CREATE_INTERACTIONS)
        for event in (STARTED, CONNECTED):
            await _deliver(_SqliteSession(in_order), event)
        expected = _row(in_order)

    for event in (CONNECTED, STARTED):
        await _deliver(_SqliteSession(db), event)

    assert _row(db) == expected
    assert expected["last_event_id"] == "evt-connected"


@pytest.mark.asyncio
async def test_earlier_event_does_not_overwrite_a_newer_one(db):
    """event-delivery: a distinct, earlier event arriving late leaves stored state unchanged."""
    session = _SqliteSession(db)
    await _deliver(session, CONNECTED)
    after_newer = _row(db)

    await _deliver(session, STARTED)

    assert _row(db) == after_newer


@pytest.mark.asyncio
async def test_duplicate_delivery_of_the_same_event_is_a_no_op(db):
    """The guard subsumes the dedup the old predicate provided: equal event time never updates."""
    session = _SqliteSession(db)
    await _deliver(session, STARTED)
    once = _row(db)

    await _deliver(session, STARTED)

    assert _row(db) == once
    assert db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_row_predating_the_guard_column_still_updates(db):
    """Rows written before `last_event_at` existed carry NULL and must not be frozen."""
    db.execute(
        "INSERT INTO interactions (interaction_id, task_id, patient_id, interaction_type, last_event_id) "
        "VALUES ('eng-1', 'task-1', 'pt-001', 'call', 'evt-legacy')"
    )

    await _deliver(_SqliteSession(db), CONNECTED)

    assert _row(db)["last_event_id"] == "evt-connected"
