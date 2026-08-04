"""Writer-state cursors — task 4.2, design decision 2's `PUT/GET /writers/{writer_id}/cursor`.

`ledger.writer_state` (migration 0001) is the store: one row per writer, a JSONB cursor and when it
was last written. The ledger-read spec's whole requirement is one property — a writer that persists
cursor C after batch N and crashes SHALL be able to restart, read C back, and resume from batch
N+1 without re-reading or re-declaring completed work. Idempotency (D16) absorbs whatever overlap
that resume still produces; this module's only job is that C comes back exactly as written.

A cursor's shape is the writer's own business (a mart's watermark, a batch offset, a resume
token); `pulse_core.cursor.validate_cursor` is the one rule imposed on it before it is stored:
JSON-native, so what a writer reads back is what it wrote and not whatever a driver silently
coerced a non-JSON value into.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb
from pulse_core.cursor import validate_cursor


@dataclass(frozen=True)
class WriterCursor:
    """One writer's durable resume point, as the ledger holds it."""

    writer_id: str
    cursor: dict[str, object]
    updated_at: datetime


def get_cursor(conn: psycopg.Connection, writer_id: str) -> WriterCursor | None:
    """The writer's persisted cursor, or `None` if it has never checkpointed one.

    `None` is a writer's first run, not an error — the crash/resume scenario only exists for a
    writer that has a cursor to come back to.
    """
    row = conn.execute(
        "SELECT writer_id, cursor, updated_at FROM ledger.writer_state WHERE writer_id = %s",
        (writer_id,),
    ).fetchone()
    if row is None:
        return None
    return WriterCursor(writer_id=row[0], cursor=row[1], updated_at=row[2])


def put_cursor(conn: psycopg.Connection, writer_id: str, cursor: object) -> WriterCursor:
    """Persist `cursor` as the writer's new resume point, replacing whatever was there.

    Raises `pulse_core.cursor.InvalidCursorError` for a cursor that is not JSON-native rather than
    storing a value the writer could not read back unchanged.
    """
    canonical = validate_cursor(cursor)
    row = conn.execute(
        "INSERT INTO ledger.writer_state (writer_id, cursor, updated_at)"
        " VALUES (%(writer_id)s, %(cursor)s, now())"
        " ON CONFLICT (writer_id) DO UPDATE SET cursor = EXCLUDED.cursor, updated_at = now()"
        " RETURNING writer_id, cursor, updated_at",
        {"writer_id": writer_id, "cursor": Jsonb(canonical)},
    ).fetchone()
    assert row is not None  # noqa: S101 — INSERT ... RETURNING always returns the row it just wrote
    return WriterCursor(writer_id=row[0], cursor=row[1], updated_at=row[2])
