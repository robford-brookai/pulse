"""The patients rebuild CLI: the operator command that replays the ledger onto `patients`.

The CLI owns three things the handler's `rebuild()` (task 1.1) deliberately does not: *which*
subjects to read, *where* their events come from, and *how* the run is configured. Everything it
writes still goes through `handle_patient_state` — these tests assert that, because a rebuild that
wrote its own SQL would be a second implementation of the monotonic guard and the read-only gate
would be the only thing left standing between it and a corrupted projection.

The ledger side is faked at the HTTP boundary (`httpx.MockTransport`) or at the history read's
shape, so no test holds a credential. The database side is the same in-memory SQLite shim
`test_patient_state.py` uses, extended with row iteration because the CLI reads the scope back out
of `patients`. Every identifier is synthetic; the PHI tripwire at the bottom plants values the CLI
has no business repeating and asserts they reach neither a log line nor the receipt.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import httpx
import pytest
import structlog

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
    """Enough of a SQLAlchemy `CursorResult` for a RETURNING clause and a scope SELECT."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _SqliteSession:
    """Enough of an async SQLAlchemy session to run the CLI's statements on SQLite."""

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


def _legacy_row(conn: sqlite3.Connection, patient_id: str, status: str = "pending") -> None:
    """A row as the retired bootstrap insert left it: a status the ledger never asserted, no citation."""
    conn.execute(
        "INSERT INTO patients (patient_id, clinic_id, enrollment_status, updated_at, last_event_id, ledger_seq) "
        "VALUES (:pid, 'clinic-legacy', :status, '2026-01-01T00:00:00+00:00', 'evt-legacy', NULL)",
        {"pid": patient_id, "status": status},
    )


def _rows(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute("SELECT * FROM patients ORDER BY patient_id")]


def make_event(
    *,
    subject_key: str = "pt-0001",
    to_state: str = "pending_start",
    seq: int = 41,
    event_id: str = "evt-0001",
    payload_extra: dict | None = None,
    clinic_id: str | None = "clinic-synth",
) -> dict:
    """A committed `enrollment` envelope as the ledger's history route serves it."""
    payload: dict = {"to_state": to_state, "program": "CCM"}
    if clinic_id is not None:
        payload["clinic_id"] = clinic_id
    if payload_extra:
        payload.update(payload_extra)
    return {
        "event_id": event_id,
        "event_type": "enrollment.declared",
        "subject_type": "enrollment",
        "subject_key": subject_key,
        "seq": seq,
        "effective_at": "2026-04-01T12:00:00+00:00",
        "payload": payload,
    }


class _FixtureHistory:
    """A `SubjectHistorySource` holding one canned history per subject, and its call log."""

    def __init__(self, histories: dict[str, list[dict]]) -> None:
        self._histories = histories
        self.calls: list[tuple[str, str]] = []

    def subject_history(self, subject_type: str, subject_key: str, *, page_size: int = 500):
        self.calls.append((subject_type, subject_key))
        return list(self._histories.get(subject_key, []))


# --- scope -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_is_every_projected_patient_id_plus_the_operator_subjects(db, session):
    """Legacy rows are in scope because adopting them is the point of the run; `--subject` adds
    subjects that have no row yet, which is the only way a rebuild can mint one."""
    from src.rebuild_patients import resolve_scope

    _legacy_row(db, "pt-0002")
    _legacy_row(db, "pt-0001")

    assert await resolve_scope(session, ("pt-0003", "pt-0001")) == ("pt-0001", "pt-0002", "pt-0003")


@pytest.mark.asyncio
async def test_the_scope_read_is_a_select_and_the_only_other_statement_is_the_handler_write(db, session):
    """Spec "Only the ledger projection mints or updates a patient row": the CLI reads the scope
    and writes nothing of its own — every mutation is the handler's one statement."""
    from src.handlers.patient_state import _APPLY_SQL
    from src.rebuild_patients import rebuild_patients

    _legacy_row(db, "pt-0001")
    history = _FixtureHistory({"pt-0001": [make_event(to_state="active", seq=7)]})

    await rebuild_patients(session, history=history)

    scope_reads = [text for text in session.statements if text != _APPLY_SQL.text]
    assert all(text.strip().upper().startswith("SELECT") for text in scope_reads)
    assert session.statements.count(_APPLY_SQL.text) == 1


# --- the run -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_cli_path_replays_the_journal_and_the_receipt_counts_match(db, session):
    from src.rebuild_patients import rebuild_patients

    _legacy_row(db, "pt-0001")
    _legacy_row(db, "pt-0002")
    history = _FixtureHistory({
        "pt-0001": [
            make_event(subject_key="pt-0001", to_state="pending_start", seq=1, event_id="evt-1"),
            make_event(subject_key="pt-0001", to_state="active", seq=2, event_id="evt-2"),
        ],
        "pt-0002": [make_event(subject_key="pt-0002", to_state="pending_start", seq=3, event_id="evt-3")],
    })

    receipt = await rebuild_patients(session, history=history)

    assert [(row["patient_id"], row["enrollment_status"], row["ledger_seq"]) for row in _rows(db)] == [
        ("pt-0001", "active", 2),
        ("pt-0002", "pending_start", 3),
    ]
    assert (receipt.events_read, receipt.subjects, receipt.applied) == (3, 2, 3)
    assert (receipt.skipped_stale, receipt.parked) == (0, 0)
    assert history.calls == [("enrollment", "pt-0001"), ("enrollment", "pt-0002")]


@pytest.mark.asyncio
async def test_a_rerun_writes_nothing_and_counts_the_second_pass_as_skips(db, session):
    """The monotonic guard is per `patient_id`, which is what makes per-subject order enough."""
    from src.rebuild_patients import rebuild_patients

    _legacy_row(db, "pt-0001")
    history = _FixtureHistory({"pt-0001": [make_event(to_state="active", seq=50)]})

    first = await rebuild_patients(session, history=history)
    before = _rows(db)
    second = await rebuild_patients(session, history=history)

    assert (first.applied, first.skipped_stale) == (1, 0)
    assert (second.applied, second.skipped_stale) == (0, 1)
    assert _rows(db) == before


@pytest.mark.asyncio
async def test_a_subject_with_no_history_is_a_counted_park_not_a_failure(db, session):
    """A legacy row the ledger has never minted an event for stays legacy: nothing to apply, no
    failure, and the run still says so in a count rather than dropping it silently."""
    from src.rebuild_patients import rebuild_patients

    _legacy_row(db, "pt-silent")
    _legacy_row(db, "pt-0001")
    history = _FixtureHistory({"pt-0001": [make_event(to_state="active", seq=9)]})

    receipt = await rebuild_patients(session, history=history)

    assert (receipt.applied, receipt.parked, receipt.subjects) == (1, 1, 1)
    silent = next(row for row in _rows(db) if row["patient_id"] == "pt-silent")
    assert (silent["enrollment_status"], silent["ledger_seq"]) == ("pending", None)


@pytest.mark.asyncio
async def test_an_unresolvable_subject_parks_and_the_run_keeps_going(db, session):
    from src.rebuild_patients import rebuild_patients

    _legacy_row(db, "pt-0001")
    history = _FixtureHistory({
        "pt-0001": [
            make_event(subject_key="   ", seq=1, event_id="evt-park"),
            make_event(subject_key="pt-0001", to_state="active", seq=2),
        ]
    })

    receipt = await rebuild_patients(session, history=history)

    assert (receipt.applied, receipt.parked, receipt.events_read) == (1, 1, 2)


# --- the reader --------------------------------------------------------------------------------


def _history_page(events: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"events": events})


def test_the_reader_pages_after_seq_to_the_end():
    """The ledger's read surface is per subject and paged; the reader must walk it to exhaustion
    or a rebuild would silently repaint from a truncated history."""
    from pulse_core.client import PulseCoreClient
    from src.rebuild_patients import LedgerJournalReader

    requests: list[httpx.Request] = []
    pages = {
        None: [make_event(seq=1, event_id="evt-1"), make_event(seq=2, event_id="evt-2")],
        "2": [make_event(seq=3, event_id="evt-3"), make_event(seq=4, event_id="evt-4")],
        "4": [make_event(seq=5, event_id="evt-5")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _history_page(pages[request.url.params.get("after_seq")])

    with PulseCoreClient(
        "https://ledger.invalid",
        writer_id="graph-projection",
        token="synthetic",
        transport=httpx.MockTransport(handler),
    ) as client:
        reader = LedgerJournalReader(history=client, subjects=("pt-0001",), page_size=2)
        events = list(reader.enrollment_events())

    assert [event["seq"] for event in events] == [1, 2, 3, 4, 5]
    assert [request.url.params.get("after_seq") for request in requests] == [None, "2", "4"]
    assert reader.subjects_without_history == 0


def test_the_reader_counts_a_subject_the_ledger_has_no_history_for():
    from src.rebuild_patients import LedgerJournalReader

    reader = LedgerJournalReader(history=_FixtureHistory({}), subjects=("pt-0001", "pt-0002"))

    assert list(reader.enrollment_events()) == []
    assert reader.subjects_without_history == 2


# --- configuration -----------------------------------------------------------------------------


def test_a_missing_variable_is_refused_naming_every_one_of_them(capsys):
    from src.rebuild_patients import main

    exit_code = main(["--target", "dev", "--operator", "synthetic-operator"], env={})

    assert exit_code == 2
    stderr = capsys.readouterr().err
    for name in ("DATABASE_URL", "PULSE_CORE_BASE_URL", "PULSE_CORE_REPLAY_TOKEN"):
        assert name in stderr


def test_a_configured_run_prints_the_receipt_and_exits_zero(db, session, capsys):
    from src.rebuild_patients import main

    _legacy_row(db, "pt-0001")
    history = _FixtureHistory({"pt-0001": [make_event(to_state="active", seq=12)]})

    exit_code = main(
        ["--target", "dev", "--operator", "synthetic-operator", "--subject", "pt-0002"],
        env={
            "DATABASE_URL": "postgresql+asyncpg://synthetic/graph",
            "PULSE_CORE_BASE_URL": "https://ledger.invalid",
            "PULSE_CORE_REPLAY_TOKEN": "synthetic",
        },
        session=session,
        history=history,
    )

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "patient-state rebuild receipt" in stdout
    assert "rows written:  1" in stdout
    # pt-0002 was named by the operator and the ledger has nothing for it: a counted park.
    assert "parked:        1" in stdout


# --- the PHI tripwire --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_payload_field_beyond_the_state_name_reaches_a_log_or_the_receipt(db, session):
    """The CLI adds a subject scope and a history read to the handler's path; neither may become a
    new way for a payload value to reach an operator's terminal or a pasted receipt."""
    from src.rebuild_patients import rebuild_patients

    planted = {
        "clinic_id": "CLINIC-MUST-NOT-BE-LOGGED",
        "note": "NOTE-MUST-NOT-BE-LOGGED",
        "date_of_birth": "DOB-MUST-NOT-BE-LOGGED",
    }
    _legacy_row(db, "pt-0001")
    _legacy_row(db, "pt-silent")
    history = _FixtureHistory({
        "pt-0001": [
            make_event(to_state="active", seq=50, clinic_id=None, payload_extra=planted),
            make_event(to_state="pending_start", seq=47, event_id="evt-late", clinic_id=None, payload_extra=planted),
        ]
    })

    with structlog.testing.capture_logs() as logs:
        receipt = await rebuild_patients(session, history=history)

    haystack = f"{logs!r}\n{receipt!r}\n{receipt.render()}"
    for value in planted.values():
        assert value not in haystack
    assert "active" in haystack
