"""Current-state enumeration, read from the ledger's own state rows.

The one property this module exists to guarantee: a clock-driven job — month-open being the case
the spec names — enumerates subjects from `ledger.current_state`, the row co-committed with the
event that changed it, and never from a projection. A projection can lag; the enumeration that
decides which Enrollments get billed this month cannot.

`current_state` holds exactly one row per subject and the commit path re-folds it in the same
transaction as the event (`commit.py`), so a plain filtered SELECT here is already the fold's
answer at read time — no re-derivation, one index (`ix_current_state_by_state`).

Requested states are validated against the catalog before the query runs. A typo'd state is a
rejection naming the catalog version, not an empty result set that reads as "no enrollments are
on hold" — the failure mode that silently skips a month of billing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from pulse_ledger.envelope import EVENT_COLUMNS, event_envelope
from pulse_ledger.validation import validate_state_membership, validate_subject_type


class NegativeLimitError(ValueError):
    """A page size below zero — a caller's arithmetic went wrong, not a request for no rows."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"limit must not be negative, got {limit}")


class UnrelayedEventError(RuntimeError):
    """A committed event with no outbox row, so the history has no sequence number for it.

    Structurally impossible through the write path — `commit.py` inserts the outbox row inside the
    same transaction as the event — which is exactly why it is raised rather than skipped. A reader
    that quietly dropped the event would hand a projection a torn history and rebuild it to a state
    the ledger never held. Names the event id and nothing else: no payload, no evidence.
    """

    def __init__(self, event_id: uuid.UUID) -> None:
        self.event_id = event_id
        super().__init__(f"committed event {event_id} has no outbox row, so its ledger sequence is unknown")


@dataclass(frozen=True)
class SubjectState:
    """One subject's current state, as the ledger holds it.

    `last_event_id` is the event this state was folded from: a reader that needs the fact behind
    the state follows it rather than re-querying by subject and hoping the row has not moved on.
    """

    subject_type: str
    subject_key: str
    state: str
    effective_at: datetime
    last_event_id: uuid.UUID
    updated_at: datetime


_SELECT_STATE = (
    "SELECT subject_type, subject_key, state, effective_at, last_event_id, updated_at"
    " FROM ledger.current_state WHERE subject_type = %(subject_type)s"
)


def enumerate_state(
    conn: psycopg.Connection,
    subject_type: str,
    states: Iterable[str] | None = None,
    *,
    after_subject_key: str | None = None,
    limit: int | None = None,
) -> list[SubjectState]:
    """Subjects of `subject_type` currently in any of `states`, in `subject_key` order.

    `states=None` enumerates every state the catalog defines for the type. Ordering is by
    `subject_key`, which is total (it is half the primary key), so `after_subject_key` + `limit`
    page the enumeration without the offset drift a mutating table gives an OFFSET scan.

    Raises `IllegalTransitionError` when the catalog does not know the subject type or one of the
    requested states.
    """
    validate_subject_type(subject_type)
    wanted: Sequence[str] | None = None
    if states is not None:
        wanted = sorted(set(states))
        for state in wanted:
            validate_state_membership(subject_type, state)
        if not wanted:
            # An empty filter asks for subjects in none of the states, which is nothing. Answering
            # it as "no filter" would enumerate the whole type instead — a caller whose state list
            # came out empty by accident would get every subject.
            return []

    query = _SELECT_STATE
    params: dict[str, object] = {"subject_type": subject_type}
    if wanted is not None:
        query += " AND state = ANY(%(states)s)"
        params["states"] = list(wanted)
    if after_subject_key is not None:
        query += " AND subject_key > %(after_subject_key)s"
        params["after_subject_key"] = after_subject_key
    query += " ORDER BY subject_key"
    if limit is not None:
        if limit < 0:
            raise NegativeLimitError(limit)
        query += " LIMIT %(limit)s"
        params["limit"] = limit

    cursor = conn.execute(query, params)
    return [
        SubjectState(
            subject_type=row[0],
            subject_key=row[1],
            state=row[2],
            effective_at=row[3],
            last_event_id=row[4],
            updated_at=row[5],
        )
        for row in cursor.fetchall()
    ]


def state_of_record(conn: psycopg.Connection, subject_type: str, subject_key: str) -> str | None:
    """One subject's current state, or `None` if the ledger has never seen the subject.

    The Twenty webhook route's echo-suppression read (twenty-projection design decision 5): the
    drag mapping compares a payload's target state against this answer to terminate the
    heal-back/projection echo loop. The same `current_state` row every other read here trusts —
    co-committed with the event, so this is the fold's answer, not a projection's.

    `None` is an answer, not an error: a subject with no state row has no state of record, and
    nothing can be an echo of it. An unknown subject *type* is still a rejection, as everywhere
    else in this module.
    """
    validate_subject_type(subject_type)
    cursor = conn.execute(
        "SELECT state FROM ledger.current_state"
        " WHERE subject_type = %(subject_type)s AND subject_key = %(subject_key)s",
        {"subject_type": subject_type, "subject_key": subject_key},
    )
    row = cursor.fetchone()
    return None if row is None else row[0]


def count_by_state(conn: psycopg.Connection, subject_type: str) -> dict[str, int]:
    """How many subjects of this type sit in each state — the enumeration's shape, without the rows.

    A state the catalog defines but no subject occupies is reported as `0` rather than omitted, so
    a caller charting the distribution does not have to know the catalog to fill the gaps.
    """
    adjacency = validate_subject_type(subject_type)
    counts = dict.fromkeys(adjacency, 0)
    cursor = conn.execute(
        "SELECT state, count(*) FROM ledger.current_state WHERE subject_type = %s GROUP BY state",
        (subject_type,),
    )
    for state, count in cursor.fetchall():
        counts[state] = count
    return counts


#: One subject's committed history, joined to the outbox row that carries the event's per-subject
#: sequence. `LEFT JOIN` rather than an inner join on purpose: an event whose outbox row is missing
#: must surface as `UnrelayedEventError`, not vanish from a history someone is about to replay.
_SELECT_HISTORY = f"""
    SELECT e.event_id, e.subject_type, e.subject_key, o.seq,
           {EVENT_COLUMNS}
      FROM ledger.events e
      LEFT JOIN ledger.outbox o USING (event_id)
     WHERE e.subject_type = %(subject_type)s AND e.subject_key = %(subject_key)s
"""  # noqa: S608 — the only interpolation is `EVENT_COLUMNS`, a module constant


def subject_history(
    conn: psycopg.Connection,
    subject_type: str,
    subject_key: str,
    *,
    after_seq: int | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Every committed event for one subject, in ledger sequence, as published envelopes.

    The replay source behind the projection rebuild (pulse-demo-closeout design decision 5). Its
    scope is exactly one subject's committed events and nothing more: no state row, no other
    subject, no derivation, no fold.

    **Ledger sequence is the outbox `seq`** — the per-subject counter `commit.py` assigns inside
    the commit transaction (D17) and the relay publishes in. It is the order a live consumer saw
    these events in and the order its watermark guard is stated over, so replaying in it is what
    makes a rebuild agree with incremental apply. It is *not* the fold's bitemporal order: a
    backdated event arrives late and replays late, exactly as it did live. A caller that wants the
    state rather than the sequence folds the result through `pulse_ledger.fold`, which owns that
    ordering rule and is the only place it is stated.

    Two further guarantees:

    - **The shape is the relay's envelope** (`envelope.event_envelope`), `seq` included, so a
      consumer written against the bus reads a replayed event without a second code path.
    - **Reversals and reversed events are present.** The fold drops them (`fold.surviving_events`);
      history does not, or a correction would be invisible to anything replaying it.

    `after_seq` with `limit` pages the history. The order is total and immutable — `seq` is unique
    per subject and never reused — so a page boundary can neither repeat nor skip an event, even
    while the subject is still being written to.

    Raises `IllegalTransitionError` for a subject type the catalog does not know (an empty result
    would read as "this subject has no history"), `NegativeLimitError` for a negative page size,
    and `UnrelayedEventError` for a committed event with no outbox row.
    """
    validate_subject_type(subject_type)
    query = _SELECT_HISTORY
    params: dict[str, object] = {"subject_type": subject_type, "subject_key": subject_key}
    if after_seq is not None:
        query += " AND o.seq > %(after_seq)s"
        params["after_seq"] = after_seq
    query += " ORDER BY o.seq"
    if limit is not None:
        if limit < 0:
            raise NegativeLimitError(limit)
        query += " LIMIT %(limit)s"
        params["limit"] = limit

    cursor = conn.cursor(row_factory=dict_row)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    for row in rows:
        if row["seq"] is None:
            raise UnrelayedEventError(row["event_id"])
    return [event_envelope(row) for row in rows]
