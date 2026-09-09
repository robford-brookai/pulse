"""Unit tests for graph projection handlers and consumer dispatch."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

sqlite3.register_adapter(datetime, lambda d: d.astimezone(UTC).isoformat())


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


# --- an alert for an unknown patient, against a real (sqlite) connection ----------------------
#
# The mock-session tests above prove *no SQL statement* touches `patients`; this one proves the
# consequence against an actual table: applying `alert.created` for a patient the ledger has never
# minted leaves `patients` empty. Only `handlers/patient_state.py` mints or updates that table
# (spec: "Only the ledger projection mints or updates a patient row").

_CREATE_TABLES = """
CREATE TABLE patients (
    patient_id        TEXT PRIMARY KEY,
    clinic_id         TEXT NOT NULL,
    enrollment_status TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    ledger_seq        INTEGER
);
CREATE TABLE alerts (
    alert_id       TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL,
    alert_type     TEXT NOT NULL,
    severity       TEXT NOT NULL,
    status         TEXT NOT NULL,
    source_system  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    last_event_id  TEXT
);
CREATE TABLE audit_log (
    audit_id      TEXT PRIMARY KEY,
    event_id      TEXT NOT NULL,
    action_type   TEXT NOT NULL,
    actor_id      TEXT NOT NULL,
    source_system TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    detail        TEXT NOT NULL
);
"""


class _SqliteSession:
    """Just enough of an async SQLAlchemy session to run a `sa.text()` clause on SQLite —
    the same offline stand-in `test_patient_state.py` uses."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    async def execute(self, clause, params=None):
        self._conn.execute(clause.text, params or {})


@pytest.fixture
def sqlite_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_CREATE_TABLES)
    yield conn
    conn.close()


def make_alert_event(alert_id="a1", patient_id="p1", clinic_id="c1"):
    return {
        "event_id": "evt-001",
        "event_type": "alert.created",
        "source_system": "pocar",
        "entity_id": alert_id,
        "entity_type": "alert",
        "correlation_id": "corr-001",
        "timestamp": "2026-03-05T10:00:00Z",
        "payload": {
            "alert_type": "glucose_missing",
            "severity": "urgent",
            "patient_id": patient_id,
            "clinic_id": clinic_id,
        },
    }


@pytest.mark.asyncio
async def test_alert_for_an_unknown_patient_mints_no_patients_row(sqlite_conn):
    """Spec scenario "An alert for an unknown patient mints nothing": the alert row lands, no
    `patients` row is created."""
    from src.handlers.alerts import handle_alert_created

    session = _SqliteSession(sqlite_conn)
    await handle_alert_created(make_alert_event(patient_id="pt-unknown"), session)

    assert sqlite_conn.execute("SELECT * FROM patients").fetchall() == []
    alert_rows = sqlite_conn.execute("SELECT alert_id, patient_id FROM alerts").fetchall()
    assert alert_rows == [("a1", "pt-unknown")]


@pytest.mark.asyncio
async def test_handle_alert_created_maps_fields(mock_session):
    """handle_alert_created calls session.execute with alerts upsert + audit_log only — no
    `patients` write. `patients` is minted only by the patient-state projection handler
    (spec: "Only the ledger projection mints or updates a patient row")."""
    from src.handlers.alerts import handle_alert_created

    await handle_alert_created(make_alert_event(), mock_session)
    assert mock_session.execute.call_count == 2  # alerts upsert + audit_log

    all_calls_str = str(mock_session.execute.call_args_list)
    assert "p1" in all_calls_str
    assert "a1" in all_calls_str
    assert "INSERT INTO patients" not in all_calls_str


@pytest.mark.asyncio
async def test_handle_alert_created_idempotent(mock_session):
    """Calling handle_alert_created twice does not raise — ON CONFLICT handles dedup at DB level."""
    from src.handlers.alerts import handle_alert_created

    event = make_alert_event()
    await handle_alert_created(event, mock_session)
    await handle_alert_created(event, mock_session)
    # Both calls complete without error; DB-level idempotency via ON CONFLICT DO UPDATE
    assert mock_session.execute.call_count == 4  # 2 per call x 2


@pytest.mark.asyncio
async def test_unknown_event_type_skipped(mock_session):
    """dispatch() with unknown event_type does not raise and does not call session.execute."""
    from src.consumer import dispatch

    await dispatch({"event_type": "future.event.type", "payload": {}}, mock_session)
    mock_session.execute.assert_not_called()


def test_no_kafka_consumer_config_remains():
    """SQS conversion (DNA-761): isolation from event-store now comes from a
    dedicated queue, not a consumer group. No Kafka config may survive."""
    import src.consumer as consumer_module

    assert not hasattr(consumer_module, "CONSUMER_CONFIG")
    assert not hasattr(consumer_module, "TOPICS")


@pytest.mark.asyncio
async def test_handle_task_claimed_updates_status(mock_session):
    """handle_task_claimed updates task status to 'claimed' and sets assigned_to from actor_id."""
    from src.handlers.tasks import handle_task_claimed

    event = {
        "event_id": "evt-claimed-001",
        "event_type": "task.claimed",
        "entity_id": "task-abc",
        "entity_type": "task",
        "timestamp": "2026-03-05T10:00:00Z",
        "payload": {"task_id": "task-abc", "actor_id": "nurse-jane"},
    }

    await handle_task_claimed(event, mock_session)

    assert mock_session.execute.called
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "claimed" in sql_text
    params = mock_session.execute.call_args[0][1]
    assert params["task_id"] == "task-abc"
    assert params["assigned_to"] == "nurse-jane"
    assert params["event_id"] == "evt-claimed-001"


def test_task_claimed_registered_in_event_handlers():
    """task.claimed is registered in EVENT_HANDLERS and dispatches to handle_task_claimed."""
    from src.consumer import EVENT_HANDLERS
    from src.handlers.tasks import handle_task_claimed

    assert "task.claimed" in EVENT_HANDLERS
    assert EVENT_HANDLERS["task.claimed"] is handle_task_claimed
