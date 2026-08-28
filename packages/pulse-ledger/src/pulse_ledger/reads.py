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

from pulse_ledger.validation import validate_state_membership, validate_subject_type


class NegativeLimitError(ValueError):
    """A page size below zero — a caller's arithmetic went wrong, not a request for no rows."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"limit must not be negative, got {limit}")


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
