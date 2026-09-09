"""The patient-state projection: what makes a `patients` row, and what may never touch one.

The write-path tests run the handler's real SQL against an in-memory SQLite database through a
minimal session shim — the same offline stand-in `test_interactions_ordering.py` uses, and for the
same reason: SQLite implements `INSERT ... ON CONFLICT DO UPDATE ... WHERE ... RETURNING` with the
semantics Postgres does for this statement, so the monotonic guard is *exercised* rather than
string-matched. No Docker, no live Postgres, no new dependency.

Every identifier here is synthetic. The PHI tripwire at the bottom is the load-bearing one: it
plants values in payload fields the projection has no business repeating and asserts they reach
neither a log line nor a rebuild receipt.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
import structlog

# SQLite has no native datetime type. Normalized UTC ISO-8601 text orders lexicographically
# exactly as the instants order, which is all the assertions below need.
sqlite3.register_adapter(datetime, lambda d: d.astimezone(UTC).isoformat())

_CREATE_PATIENTS = """
CREATE TABLE patients (
    patient_id        TEXT PRIMARY KEY,
    clinic_id         TEXT NOT NULL,
    enrollment_status TEXT NOT NULL,
    enrolled_at       TEXT,
    updated_at        TEXT NOT NULL,
    last_event_id     TEXT,
    ledger_seq        INTEGER
)
"""


class _SqliteResult:
    """Just enough of a SQLAlchemy `CursorResult` for a RETURNING clause."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _SqliteSession:
    """Just enough of an async SQLAlchemy session to run a `sa.text()` clause on SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.statements: list[str] = []

    async def execute(self, clause, params=None):
        self.statements.append(clause.text)
        cursor = self._conn.execute(clause.text, params or {})
        return _SqliteResult(cursor.fetchall())


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute(_CREATE_PATIENTS)
    yield conn
    conn.close()


@pytest.fixture
def session(db):
    return _SqliteSession(db)


def _row(conn: sqlite3.Connection, patient_id: str = "pt-0001") -> dict | None:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM patients WHERE patient_id = :pid", {"pid": patient_id})
    found = cursor.fetchone()
    return dict(found) if found is not None else None


def _rows(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute("SELECT * FROM patients ORDER BY patient_id")]


def _legacy_row(conn: sqlite3.Connection, patient_id: str = "pt-0001", status: str = "pending") -> None:
    """A row as the retired bootstrap insert left it: a status the ledger never asserted, no citation."""
    conn.execute(
        "INSERT INTO patients (patient_id, clinic_id, enrollment_status, updated_at, last_event_id, ledger_seq) "
        "VALUES (:pid, 'clinic-legacy', :status, '2026-01-01T00:00:00+00:00', 'evt-legacy', NULL)",
        {"pid": patient_id, "status": status},
    )


def make_event(
    *,
    subject_key: str = "pt-0001",
    to_state: str = "pending_start",
    seq: int = 41,
    event_id: str = "evt-0001",
    payload_extra: dict | None = None,
    clinic_id: str | None = "clinic-synth",
    subject_type: str = "enrollment",
) -> dict:
    """A committed `enrollment` envelope as the ledger relay publishes it onto `patient-state`."""
    payload: dict = {"to_state": to_state, "program": "CCM"}
    if clinic_id is not None:
        payload["clinic_id"] = clinic_id
    if payload_extra:
        payload.update(payload_extra)
    return {
        "event_id": event_id,
        "event_type": "enrollment.declared",
        "subject_type": subject_type,
        "subject_key": subject_key,
        "seq": seq,
        "effective_at": "2026-04-01T12:00:00+00:00",
        "payload": payload,
    }


# --- minting ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_enrollment_event_mints_the_row(db, session):
    """Spec "First enrollment event mints the row": status and citation both come from the event."""
    from src.handlers.patient_state import Applied, ProjectionMetrics, handle_patient_state

    metrics = ProjectionMetrics()
    result = await handle_patient_state(make_event(to_state="pending_start", seq=41), session, metrics=metrics)

    assert isinstance(result, Applied)
    assert (result.patient_id, result.seq, result.to_state) == ("pt-0001", 41, "pending_start")
    row = _row(db)
    assert row is not None
    assert row["enrollment_status"] == "pending_start"
    assert row["ledger_seq"] == 41
    assert row["last_event_id"] == "evt-0001"
    assert metrics.applied == 1
    assert metrics.skipped_stale == 0
    assert metrics.parked == 0


@pytest.mark.asyncio
async def test_mint_takes_clinic_id_from_the_payload_when_it_carries_one(db, session):
    from src.handlers.patient_state import handle_patient_state

    await handle_patient_state(make_event(clinic_id="clinic-synth"), session)

    row = _row(db)
    assert row is not None
    assert row["clinic_id"] == "clinic-synth"


@pytest.mark.asyncio
async def test_mint_falls_back_to_the_unscoped_sentinel_without_a_clinic_id(db, session):
    """`clinic_id` is NOT NULL and is not ledger-sourced: absent or blank mints the sentinel."""
    from src.handlers.patient_state import UNSCOPED_CLINIC_ID, handle_patient_state

    await handle_patient_state(make_event(clinic_id=None, subject_key="pt-0001"), session)
    await handle_patient_state(make_event(clinic_id="   ", subject_key="pt-0002"), session)

    assert [row["clinic_id"] for row in _rows(db)] == [UNSCOPED_CLINIC_ID, UNSCOPED_CLINIC_ID]


@pytest.mark.asyncio
async def test_a_later_event_moves_the_row_forward(db, session):
    from src.handlers.patient_state import Applied, handle_patient_state

    await handle_patient_state(make_event(to_state="active", seq=50), session)
    result = await handle_patient_state(make_event(to_state="ended", seq=60, event_id="evt-0002"), session)

    assert isinstance(result, Applied)
    row = _row(db)
    assert row is not None
    assert (row["enrollment_status"], row["ledger_seq"], row["last_event_id"]) == ("ended", 60, "evt-0002")


# --- monotonicity ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_late_event_does_not_regress_state_and_is_counted(db, session):
    """Spec "A late event does not regress state": an older sequence is a counted no-op."""
    from src.handlers.patient_state import ProjectionMetrics, SkippedStale, handle_patient_state

    metrics = ProjectionMetrics()
    await handle_patient_state(make_event(to_state="active", seq=50), session, metrics=metrics)
    result = await handle_patient_state(
        make_event(to_state="pending_start", seq=47, event_id="evt-late"), session, metrics=metrics
    )

    assert isinstance(result, SkippedStale)
    assert (result.patient_id, result.seq) == ("pt-0001", 47)
    row = _row(db)
    assert row is not None
    assert (row["enrollment_status"], row["ledger_seq"], row["last_event_id"]) == ("active", 50, "evt-0001")
    assert (metrics.applied, metrics.skipped_stale) == (1, 1)


@pytest.mark.asyncio
async def test_redelivery_leaves_the_row_unchanged(db, session):
    """At-least-once delivery: the same event twice writes once and counts the second as a skip."""
    from src.handlers.patient_state import Applied, ProjectionMetrics, SkippedStale, handle_patient_state

    metrics = ProjectionMetrics()
    event = make_event(to_state="active", seq=50)
    first = await handle_patient_state(event, session, metrics=metrics)
    before = _row(db)
    second = await handle_patient_state(event, session, metrics=metrics)

    assert isinstance(first, Applied)
    assert isinstance(second, SkippedStale)
    assert _row(db) == before
    assert (metrics.applied, metrics.skipped_stale) == (1, 1)


# --- legacy rows -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_legacy_row_is_adopted_by_the_first_ledger_event(db, session):
    """Spec "Genesis adopts a legacy row": a null citation is adoptable at any sequence."""
    from src.handlers.patient_state import Applied, handle_patient_state

    _legacy_row(db, status="pending")

    result = await handle_patient_state(make_event(to_state="active", seq=12, event_id="evt-adopt"), session)

    assert isinstance(result, Applied)
    row = _row(db)
    assert row is not None
    assert (row["enrollment_status"], row["ledger_seq"], row["last_event_id"]) == ("active", 12, "evt-adopt")


@pytest.mark.asyncio
async def test_adoption_leaves_clinic_id_alone(db, session):
    """`clinic_id` is not ledger-sourced, so an adopt never overwrites the value the row carries."""
    from src.handlers.patient_state import handle_patient_state

    _legacy_row(db)

    await handle_patient_state(make_event(clinic_id="clinic-synth", to_state="active", seq=12), session)

    row = _row(db)
    assert row is not None
    assert row["clinic_id"] == "clinic-legacy"


@pytest.mark.asyncio
async def test_a_legacy_row_is_untouched_until_its_event_arrives(db, session):
    """No ledger event for this subject: another subject's event must not read on the legacy row."""
    from src.handlers.patient_state import handle_patient_state

    _legacy_row(db, patient_id="pt-legacy", status="pending")

    await handle_patient_state(make_event(subject_key="pt-0001", to_state="active", seq=9), session)

    legacy = _row(db, "pt-legacy")
    assert legacy is not None
    assert (legacy["enrollment_status"], legacy["ledger_seq"]) == ("pending", None)


# --- parking and refusal ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unresolvable_subject_parks_and_writes_nothing(db, session):
    """Spec: a subject that resolves to no canonical patient id parks, counted, without raising."""
    from src.handlers.patient_state import UNRESOLVED_SUBJECT, Parked, ProjectionMetrics, handle_patient_state

    metrics = ProjectionMetrics()
    result = await handle_patient_state(
        make_event(subject_key="pt-unknown"), session, resolver=lambda _key: None, metrics=metrics
    )

    assert isinstance(result, Parked)
    assert (result.subject_key, result.reason) == ("pt-unknown", UNRESOLVED_SUBJECT)
    assert _rows(db) == []
    assert (metrics.parked, metrics.applied) == (1, 0)


@pytest.mark.asyncio
async def test_a_blank_subject_key_parks_through_the_default_resolver(db, session):
    from src.handlers.patient_state import UNRESOLVED_SUBJECT, Parked, handle_patient_state

    result = await handle_patient_state(make_event(subject_key="   "), session)

    assert isinstance(result, Parked)
    assert result.reason == UNRESOLVED_SUBJECT
    assert _rows(db) == []


@pytest.mark.asyncio
async def test_the_consumer_continues_after_a_parked_subject(db, session):
    """A park is a normal return, so the next event on the queue still lands."""
    from src.consumer import dispatch

    await dispatch(make_event(subject_key="   ", seq=7), session)
    await dispatch(make_event(subject_key="pt-0001", to_state="active", seq=8), session)

    assert [(row["patient_id"], row["enrollment_status"]) for row in _rows(db)] == [("pt-0001", "active")]


@pytest.mark.asyncio
async def test_the_state_name_is_written_verbatim_and_never_re_validated(db, session):
    """The ledger is the single validator of catalog vocabulary
    (`pulse_ledger.validation.validate_transition`), so the projection writes `to_state` through.

    The state below is deliberately not in `enrollment` today: a consumer that re-encoded the
    family would park it, which is exactly how a catalog version bump would silently stall the
    projection. Writing it through is the behaviour under test, not an accident.
    """
    from src.handlers.patient_state import Applied, handle_patient_state

    future_state = "paused_pending_review"
    result = await handle_patient_state(make_event(to_state=future_state, seq=41), session)

    assert isinstance(result, Applied)
    assert result.to_state == future_state
    row = _row(db)
    assert row is not None
    assert (row["enrollment_status"], row["ledger_seq"]) == (future_state, 41)


@pytest.mark.parametrize(
    ("mutation", "field_path"),
    [
        ({"event_id": ""}, "event_id"),
        ({"subject_key": 7}, "subject_key"),
        ({"seq": "41"}, "seq"),
        ({"seq": True}, "seq"),
        ({"payload": []}, "payload"),
        ({"subject_type": "consent"}, "subject_type"),
    ],
)
@pytest.mark.asyncio
async def test_a_malformed_envelope_names_only_the_field_path(session, mutation, field_path):
    from src.handlers.patient_state import MalformedEventError, parse_envelope

    envelope = make_event() | mutation
    with pytest.raises(MalformedEventError) as raised:
        parse_envelope(envelope)
    assert raised.value.field_path == field_path


@pytest.mark.asyncio
async def test_a_malformed_envelope_parks_rather_than_failing_the_consumer(db, session):
    """A message the relay could not have published is not fixed by redelivery: it parks, counted,
    with the field path as the reason and no value from the envelope anywhere in it."""
    from src.handlers.patient_state import Parked, ProjectionMetrics, handle_patient_state

    metrics = ProjectionMetrics()
    envelope = make_event()
    envelope["seq"] = "41"

    result = await handle_patient_state(envelope, session, metrics=metrics)

    assert isinstance(result, Parked)
    assert (result.reason, result.subject_key, result.event_id) == ("seq", "pt-0001", "evt-0001")
    assert metrics.parked == 1
    assert _rows(db) == []


@pytest.mark.asyncio
async def test_a_missing_to_state_is_malformed(session):
    from src.handlers.patient_state import MalformedEventError, parse_envelope

    envelope = make_event()
    del envelope["payload"]["to_state"]
    with pytest.raises(MalformedEventError) as raised:
        parse_envelope(envelope)
    assert raised.value.field_path == "payload.to_state"


# --- dispatch --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_routes_an_enrollment_subject_to_the_projection(db, session):
    from src.consumer import dispatch

    await dispatch(make_event(to_state="on_hold", seq=88), session)

    row = _row(db)
    assert row is not None
    assert (row["enrollment_status"], row["ledger_seq"]) == ("on_hold", 88)


@pytest.mark.asyncio
async def test_dispatch_ignores_a_ledger_subject_the_projection_does_not_render(db, session):
    from src.consumer import dispatch

    await dispatch(make_event(subject_type="consent"), session)

    assert _rows(db) == []


# --- rebuild ---------------------------------------------------------------------------------


class _FixtureJournal:
    """A `JournalReader` holding one canned journal — the rebuild depends on the read's shape."""

    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def enrollment_events(self):
        return list(self._events)


@pytest.mark.asyncio
async def test_rebuild_replays_the_journal_and_receipts_it(db, session):
    from src.handlers.patient_state import rebuild

    journal = _FixtureJournal([
        make_event(subject_key="pt-0001", to_state="pending_start", seq=1, event_id="evt-1"),
        make_event(subject_key="pt-0001", to_state="active", seq=2, event_id="evt-2"),
        make_event(subject_key="pt-0002", to_state="pending_start", seq=3, event_id="evt-3"),
    ])

    receipt = await rebuild(journal, session)

    assert [(row["patient_id"], row["enrollment_status"], row["ledger_seq"]) for row in _rows(db)] == [
        ("pt-0001", "active", 2),
        ("pt-0002", "pending_start", 3),
    ]
    assert (receipt.events_read, receipt.applied, receipt.subjects) == (3, 3, 2)
    assert (receipt.skipped_stale, receipt.parked) == (0, 0)


@pytest.mark.asyncio
async def test_rebuild_is_idempotent_and_counts_the_second_pass_as_skips(db, session):
    from src.handlers.patient_state import rebuild

    journal = _FixtureJournal([make_event(to_state="active", seq=50)])

    first = await rebuild(journal, session)
    before = _row(db)
    second = await rebuild(journal, session)

    assert (first.applied, first.skipped_stale) == (1, 0)
    assert (second.applied, second.skipped_stale) == (0, 1)
    assert _row(db) == before


@pytest.mark.asyncio
async def test_rebuild_parks_an_unresolvable_subject_and_keeps_going(db, session):
    from src.handlers.patient_state import rebuild

    journal = _FixtureJournal([
        make_event(subject_key="   ", seq=1, event_id="evt-park"),
        make_event(subject_key="pt-0001", to_state="active", seq=2),
    ])

    receipt = await rebuild(journal, session)

    assert (receipt.parked, receipt.applied, receipt.events_read) == (1, 1, 2)
    assert [row["patient_id"] for row in _rows(db)] == ["pt-0001"]


# --- the PHI tripwire ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_payload_field_beyond_the_state_name_reaches_a_log_or_a_receipt(db, session):
    """The projection reads `to_state` for the column and `clinic_id` for a NOT NULL mint. Neither
    that clinic value nor any other payload field may appear in a log line or a rebuild receipt —
    the receipt is pasted onto issues, and the payload is where PHI will live once C1 clears."""
    from src.handlers.patient_state import rebuild

    planted = {
        "clinic_id": "CLINIC-MUST-NOT-BE-LOGGED",
        "note": "NOTE-MUST-NOT-BE-LOGGED",
        "date_of_birth": "DOB-MUST-NOT-BE-LOGGED",
    }
    journal = _FixtureJournal([
        make_event(to_state="active", seq=50, clinic_id=None, payload_extra=planted),
        make_event(to_state="pending_start", seq=47, event_id="evt-late", clinic_id=None, payload_extra=planted),
        make_event(subject_key="   ", seq=51, event_id="evt-park", clinic_id=None, payload_extra=planted),
    ])

    with structlog.testing.capture_logs() as logs:
        receipt = await rebuild(journal, session)

    haystack = f"{logs!r}\n{receipt!r}\n{receipt.render()}"
    for value in planted.values():
        assert value not in haystack
    # The state name is the one payload field that is meant to travel, and the row proves the
    # planted clinic value reached the database column it belongs in and nowhere else.
    assert "active" in haystack
    row = _row(db)
    assert row is not None
    assert row["clinic_id"] == planted["clinic_id"]
