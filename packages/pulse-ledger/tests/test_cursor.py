"""Writer-state cursors — task 4.2's crash/resume round-trip, against a real Postgres.

The spec scenario is one property: a writer persists cursor C after batch N, "crashes" (a fresh
connection stands in for the restart), reads its cursor back, and gets exactly C — batch N, not
N-1 or a stale value a second writer left behind.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest
from pulse_core.cursor import InvalidCursorError
from pulse_ledger.cursor import WriterCursor, get_cursor, put_cursor

# --- the spec scenario: crash and resume ------------------------------------------------------


def test_a_fresh_writer_has_no_cursor_yet(ledger_db: psycopg.Connection) -> None:
    assert get_cursor(ledger_db, "verdict-relay") is None


def test_crash_and_resume_reads_back_the_persisted_cursor(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    put_cursor(ledger_db, "verdict-relay", {"batch": 4, "computed_at": "2026-08-03T00:00:00+00:00"})

    # A second connection stands in for the writer restarting after a crash: nothing about the
    # cursor it reads back may depend on the connection that wrote it.
    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as resumed:
        cursor = get_cursor(resumed, "verdict-relay")

    assert cursor is not None
    assert cursor.cursor == {"batch": 4, "computed_at": "2026-08-03T00:00:00+00:00"}
    assert cursor.writer_id == "verdict-relay"


def test_a_later_checkpoint_replaces_the_earlier_one(ledger_db: psycopg.Connection) -> None:
    put_cursor(ledger_db, "verdict-relay", {"batch": 4})
    put_cursor(ledger_db, "verdict-relay", {"batch": 5})

    cursor = get_cursor(ledger_db, "verdict-relay")

    assert cursor is not None
    assert cursor.cursor == {"batch": 5}


def test_updated_at_advances_on_each_checkpoint(ledger_db: psycopg.Connection) -> None:
    first = put_cursor(ledger_db, "verdict-relay", {"batch": 1})
    second = put_cursor(ledger_db, "verdict-relay", {"batch": 2})

    assert second.updated_at >= first.updated_at


# --- writers do not share cursors --------------------------------------------------------------


def test_writers_have_independent_cursors(ledger_db: psycopg.Connection) -> None:
    put_cursor(ledger_db, "verdict-relay", {"batch": 4})
    put_cursor(ledger_db, "scheduler", {"batch": 9})

    assert get_cursor(ledger_db, "verdict-relay").cursor == {"batch": 4}  # type: ignore[union-attr]
    assert get_cursor(ledger_db, "scheduler").cursor == {"batch": 9}  # type: ignore[union-attr]


# --- a cursor is JSON-native --------------------------------------------------------------------


def test_a_non_json_native_cursor_is_rejected_and_nothing_is_stored(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(InvalidCursorError):
        put_cursor(ledger_db, "verdict-relay", {"as_of": datetime(2026, 8, 3, tzinfo=timezone.utc)})

    assert get_cursor(ledger_db, "verdict-relay") is None


def test_put_cursor_returns_a_writer_cursor(ledger_db: psycopg.Connection) -> None:
    result = put_cursor(ledger_db, "verdict-relay", {"batch": 1})
    assert isinstance(result, WriterCursor)
    assert result.writer_id == "verdict-relay"
