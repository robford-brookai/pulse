"""The quarantine review queue: pending, countable, and drained only by a declared resolution.

When the deterministic matcher finds more than one candidate it does not guess — a wrong auto-merge
in a HIPAA system is a reportable event. The referral stays where it is with a `resolution_hold`
fact against it and a row lands here, which is the work list the quarantine reviewer role drains
(`design/delivery/pulse-s1-work-orders.md` §S1.4, `pulse-runtime-readiness.md` §3).

Three properties this module holds:

- **Countable while pending.** `count_pending` is the queue-depth metric the reviewer role is
  staffed against, and it reads the same rows the listing does.
- **One pending review per subject.** Enforced by a partial unique index (migration 0003), so a
  retried quarantine is a replay rather than a second row for the same referral.
- **Exit only by declaration.** `resolve_review` requires the `event_id` of the resolution the
  reviewer declared through the command path, and the store requires it too: a non-pending row that
  names no resolution violates a check constraint. Closing the queue is therefore never something a
  read-side caller can do by flipping a flag.

The reviewer role is checked here as a parameter. Task 3.4 resolves credentials to actors and
authorities; until then the caller passes the authority it was granted, and this module refuses
anything other than the quarantine reviewer — the same check, one layer earlier than the transport.

Candidate sets are person keys, never demographics: the reviewer reads the evidence through the
resolver's own record, and the queue holds only the pseudonymous keys that point at it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from pulse_ledger.commit import UnknownEventError
from pulse_ledger.validation import validate_subject_type

#: The authority that may drain the queue (`pulse-runtime-readiness.md` §3, "Quarantine reviewer").
REVIEWER_ROLE = "quarantine_reviewer"


class NotReviewerError(PermissionError):
    """A caller without the quarantine reviewer authority tried to drain a review."""

    def __init__(self, role: str | None) -> None:
        self.role = role
        super().__init__(f"draining the review queue requires the {REVIEWER_ROLE!r} authority, not {role!r}")


class UnknownReviewError(LookupError):
    """No such review row."""

    def __init__(self, review_id: uuid.UUID) -> None:
        self.review_id = review_id
        super().__init__(f"no review {review_id}")


class AlreadyResolvedError(ValueError):
    """The review has already left the queue; a second resolution would rewrite the first."""

    def __init__(self, review_id: uuid.UUID) -> None:
        self.review_id = review_id
        super().__init__(f"review {review_id} is already resolved")


class SubjectAlreadyPendingError(ValueError):
    """The subject already has a pending review, so a second quarantine would double-enqueue it."""

    def __init__(self, subject_type: str, subject_key: str, review_id: uuid.UUID) -> None:
        self.subject_type = subject_type
        self.subject_key = subject_key
        self.review_id = review_id
        super().__init__(f"{subject_type}/{subject_key} is already pending review as {review_id}")


class NonKeyCandidateError(TypeError):
    """A candidate set carrying something other than person keys.

    Demographics are what a candidate set is tempting to carry and exactly what must not land in the
    ledger: the reviewer follows the keys to the resolver's evidence instead.
    """

    def __init__(self) -> None:
        super().__init__("candidates must be person keys (strings); demographics must not reach the ledger")


@dataclass(frozen=True)
class ReviewItem:
    """One quarantined subject awaiting — or having received — human adjudication."""

    review_id: uuid.UUID
    subject_type: str
    subject_key: str
    hold_event_id: uuid.UUID
    candidates: tuple[str, ...]
    pending: bool
    created_at: datetime
    resolved_at: datetime | None
    resolution_event_id: uuid.UUID | None


#: Every column a `ReviewItem` is built from, in `_item`'s order. Named once so the SELECT and the
#: two RETURNING clauses cannot drift apart. Literal, so no caller input reaches SQL as text.
_REVIEW_COLUMNS = (
    "review_id, subject_type, subject_key, hold_event_id, candidates, pending,"
    " created_at, resolved_at, resolution_event_id"
)

_SELECT_REVIEW = f"SELECT {_REVIEW_COLUMNS} FROM ledger.review_queue"  # noqa: S608 - literal columns


def _item(row: Sequence[object]) -> ReviewItem:
    # `candidates` arrives as the decoded JSONB value; the column's default is `[]` and
    # `quarantine_subject` only ever writes a list of keys, so anything else is not a candidate set.
    candidates = row[4] if isinstance(row[4], list) else []
    return ReviewItem(
        review_id=row[0],  # type: ignore[arg-type]
        subject_type=str(row[1]),
        subject_key=str(row[2]),
        hold_event_id=row[3],  # type: ignore[arg-type]
        candidates=tuple(str(candidate) for candidate in candidates),
        pending=bool(row[5]),
        created_at=row[6],  # type: ignore[arg-type]
        resolved_at=row[7],  # type: ignore[arg-type]
        resolution_event_id=row[8],  # type: ignore[arg-type]
    )


def quarantine_subject(
    conn: psycopg.Connection,
    *,
    subject_type: str,
    subject_key: str,
    hold_event_id: uuid.UUID,
    candidates: Iterable[str] = (),
) -> ReviewItem:
    """Enqueue a held subject with the candidate set that made it ambiguous.

    `hold_event_id` is the committed `resolution_hold` fact that holds the subject; the store's
    foreign key is what makes "held" mean an event exists, so a queue row can never point at a hold
    that was never declared.

    Raises `SubjectAlreadyPendingError` if the subject is already pending, `UnknownEventError` if the
    hold event is not in the ledger, and `IllegalTransitionError` for a subject type the catalog does
    not define.
    """
    validate_subject_type(subject_type)
    keys = list(candidates)
    if any(not isinstance(candidate, str) for candidate in keys):
        raise NonKeyCandidateError
    try:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO ledger.review_queue (subject_type, subject_key, hold_event_id, candidates)"  # noqa: S608
                " VALUES (%(subject_type)s, %(subject_key)s, %(hold_event_id)s, %(candidates)s)"
                f" RETURNING {_REVIEW_COLUMNS}",
                {
                    "subject_type": subject_type,
                    "subject_key": subject_key,
                    "hold_event_id": hold_event_id,
                    "candidates": Jsonb(keys),
                },
            ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        pending = _pending_for_subject(conn, subject_type, subject_key)
        if pending is None:  # pragma: no cover - the colliding row cannot vanish; nothing deletes it
            raise
        raise SubjectAlreadyPendingError(subject_type, subject_key, pending.review_id) from exc
    except psycopg.errors.ForeignKeyViolation as exc:
        raise UnknownEventError(hold_event_id) from exc
    return _item(row)  # type: ignore[arg-type]


def _pending_for_subject(conn: psycopg.Connection, subject_type: str, subject_key: str) -> ReviewItem | None:
    row = conn.execute(
        f"{_SELECT_REVIEW} WHERE subject_type = %s AND subject_key = %s AND pending",
        (subject_type, subject_key),
    ).fetchone()
    return None if row is None else _item(row)


def list_review_queue(
    conn: psycopg.Connection,
    *,
    subject_type: str | None = None,
    pending: bool | None = True,
    limit: int | None = None,
) -> list[ReviewItem]:
    """The queue in arrival order — oldest first, because that is the order a reviewer drains it.

    `pending=True` (the default) is the work list; `pending=None` includes resolved rows, which stay
    in the table as the record of what was adjudicated and by which declaration.
    """
    query = _SELECT_REVIEW
    clauses: list[str] = []
    params: dict[str, object] = {}
    if subject_type is not None:
        validate_subject_type(subject_type)
        clauses.append("subject_type = %(subject_type)s")
        params["subject_type"] = subject_type
    if pending is not None:
        clauses.append("pending" if pending else "NOT pending")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at, review_id"
    if limit is not None:
        query += " LIMIT %(limit)s"
        params["limit"] = limit
    return [_item(row) for row in conn.execute(query, params).fetchall()]


def count_pending(conn: psycopg.Connection, *, subject_type: str | None = None) -> int:
    """How many subjects are waiting on a reviewer — the queue-depth metric."""
    query = "SELECT count(*) FROM ledger.review_queue WHERE pending"
    params: dict[str, object] = {}
    if subject_type is not None:
        validate_subject_type(subject_type)
        query += " AND subject_type = %(subject_type)s"
        params["subject_type"] = subject_type
    count: int = conn.execute(query, params).fetchone()[0]  # type: ignore[index]
    return count


def resolve_review(
    conn: psycopg.Connection,
    review_id: uuid.UUID,
    *,
    reviewer_role: str | None,
    resolution_event_id: uuid.UUID,
) -> ReviewItem:
    """Drain one review by naming the resolution the reviewer declared.

    Raises `NotReviewerError` before touching the store for any authority other than the quarantine
    reviewer, `UnknownEventError` if the named resolution is not a committed event, and
    `UnknownReviewError` / `AlreadyResolvedError` when there is no pending row to drain.
    """
    if reviewer_role != REVIEWER_ROLE:
        raise NotReviewerError(reviewer_role)
    try:
        with conn.transaction():
            row = conn.execute(
                "UPDATE ledger.review_queue SET pending = false, resolved_at = now(),"
                " resolution_event_id = %(resolution_event_id)s"
                " WHERE review_id = %(review_id)s AND pending"
                " RETURNING review_id, subject_type, subject_key, hold_event_id, candidates, pending,"
                " created_at, resolved_at, resolution_event_id",
                {"review_id": review_id, "resolution_event_id": resolution_event_id},
            ).fetchone()
    except psycopg.errors.ForeignKeyViolation as exc:
        raise UnknownEventError(resolution_event_id) from exc
    if row is None:
        existing = conn.execute(
            "SELECT pending FROM ledger.review_queue WHERE review_id = %s",
            (review_id,),
        ).fetchone()
        if existing is None:
            raise UnknownReviewError(review_id)
        raise AlreadyResolvedError(review_id)
    return _item(row)
