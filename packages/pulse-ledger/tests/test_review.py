"""The quarantine review queue — pending, countable, drained only by a declared resolution.

The spec scenario: a referral quarantined with a `resolution_hold` fact appears as pending with its
candidate set, and after a reviewer declares the resolution it no longer appears. Around it: the
queue-depth count, the one-pending-row-per-subject rule, and the two ways a drain is refused —
without the reviewer authority, and without a committed resolution to name.

The hold fact is inserted directly here rather than committed through `commit_declaration`, because
a `resolution_hold` is not state-bearing (the referral stays in `received`) and the commit path has
no non-state-bearing vocabulary yet — task 3.5 introduces the first one, `reconstruction_gap`. See
HANDOFF.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_ledger.commit import Declaration, UnknownEventError, commit_declaration
from pulse_ledger.review import (
    REVIEWER_ROLE,
    AlreadyResolvedError,
    NonKeyCandidateError,
    NotReviewerError,
    SubjectAlreadyPendingError,
    UnknownReviewError,
    count_pending,
    list_review_queue,
    quarantine_subject,
    resolve_review,
)
from pulse_ledger.validation import IllegalTransitionError

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

PERSON_A = "tide-000000000000000a"
PERSON_B = "tide-000000000000000b"


def _received(conn: psycopg.Connection, subject_key: str) -> Any:
    """A referral in `received` — where a held referral stays while it waits for a reviewer."""
    return commit_declaration(
        conn,
        Declaration(
            subject_type="referral",
            subject_key=subject_key,
            event_type="referral.received",
            to_state="received",
            effective_at=T0,
            actor_type="system",
            actor_id="intake",
            producer="pulse-ledger-tests",
        ),
    )


def _hold_fact(conn: psycopg.Connection, subject_key: str) -> uuid.UUID:
    """The `resolution_hold` fact that holds the referral: an event bearing no state of its own."""
    event_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO ledger.events (event_id, subject_type, subject_key, event_type, effective_at,"
        " producer, rule_version, actor_type, actor_id)"
        " VALUES (%s, 'referral', %s, 'resolution_hold', %s, 'identity-resolver', 'appendix-c-v0.7',"
        " 'system', 'identity-resolver')",
        (event_id, subject_key, T0 + timedelta(minutes=1)),
    )
    return event_id


def _quarantine(
    conn: psycopg.Connection, subject_key: str = "ref-1", candidates: tuple[str, ...] = (PERSON_A, PERSON_B)
) -> Any:
    _received(conn, subject_key)
    return quarantine_subject(
        conn,
        subject_type="referral",
        subject_key=subject_key,
        hold_event_id=_hold_fact(conn, subject_key),
        candidates=candidates,
    )


def _declare_resolution(conn: psycopg.Connection, subject_key: str = "ref-1") -> uuid.UUID:
    """What a reviewer's disposition is: a declared `received → resolved` transition."""
    result = commit_declaration(
        conn,
        Declaration(
            subject_type="referral",
            subject_key=subject_key,
            event_type="resolve_referral",
            to_state="resolved",
            effective_at=T0 + timedelta(hours=2),
            actor_type="human",
            actor_id="reviewer-1",
            actor_authority=REVIEWER_ROLE,
            producer="pulse-ledger-tests",
        ),
    )
    return result.event_id


# --- the spec scenario: countable while pending, drained by declaration -----------------------


def test_a_quarantined_referral_is_pending_with_its_candidate_set(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)

    (listed,) = list_review_queue(ledger_db)

    assert listed.review_id == queued.review_id
    assert listed.pending is True
    assert listed.subject_key == "ref-1"
    assert listed.candidates == (PERSON_A, PERSON_B)
    assert listed.resolution_event_id is None
    assert count_pending(ledger_db) == 1
    # The referral itself has not moved: it waits in `received`.
    assert ledger_db.execute("SELECT state FROM ledger.current_state WHERE subject_key = 'ref-1'").fetchone() == (
        "received",
    )


def test_a_reviewers_declared_resolution_drains_the_queue(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)
    resolution = _declare_resolution(ledger_db)

    resolved = resolve_review(
        ledger_db,
        queued.review_id,
        reviewer_role=REVIEWER_ROLE,
        resolution_event_id=resolution,
    )

    assert resolved.pending is False
    assert resolved.resolution_event_id == resolution
    assert resolved.resolved_at is not None
    assert list_review_queue(ledger_db) == []
    assert count_pending(ledger_db) == 0
    # The row stays as the record of what was adjudicated, and by which declaration.
    (history,) = list_review_queue(ledger_db, pending=None)
    assert history.resolution_event_id == resolution


# --- who may drain it, and on what evidence ---------------------------------------------------


def test_a_caller_without_the_reviewer_authority_cannot_drain_a_review(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)
    resolution = _declare_resolution(ledger_db)

    with pytest.raises(NotReviewerError):
        resolve_review(ledger_db, queued.review_id, reviewer_role="verdict-relay", resolution_event_id=resolution)
    with pytest.raises(NotReviewerError):
        resolve_review(ledger_db, queued.review_id, reviewer_role=None, resolution_event_id=resolution)

    assert count_pending(ledger_db) == 1


def test_a_drain_must_name_a_committed_resolution(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)

    with pytest.raises(UnknownEventError):
        resolve_review(
            ledger_db,
            queued.review_id,
            reviewer_role=REVIEWER_ROLE,
            resolution_event_id=uuid.uuid4(),
        )

    assert count_pending(ledger_db) == 1


def test_the_store_refuses_a_resolved_row_that_names_no_resolution(ledger_db: psycopg.Connection) -> None:
    """ "Left the queue" and "names its resolution" are one state, so no flag flip can drain a row."""
    queued = _quarantine(ledger_db)

    with pytest.raises(psycopg.errors.CheckViolation):
        ledger_db.execute(
            "UPDATE ledger.review_queue SET pending = false WHERE review_id = %s",
            (queued.review_id,),
        )


def test_resolving_twice_is_refused(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)
    resolution = _declare_resolution(ledger_db)
    resolve_review(ledger_db, queued.review_id, reviewer_role=REVIEWER_ROLE, resolution_event_id=resolution)

    with pytest.raises(AlreadyResolvedError):
        resolve_review(ledger_db, queued.review_id, reviewer_role=REVIEWER_ROLE, resolution_event_id=resolution)


def test_resolving_an_unknown_review_is_refused(ledger_db: psycopg.Connection) -> None:
    _quarantine(ledger_db)
    resolution = _declare_resolution(ledger_db)

    with pytest.raises(UnknownReviewError):
        resolve_review(ledger_db, uuid.uuid4(), reviewer_role=REVIEWER_ROLE, resolution_event_id=resolution)


# --- entering the queue -----------------------------------------------------------------------


def test_a_subject_can_only_be_pending_once(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)

    with pytest.raises(SubjectAlreadyPendingError) as raised:
        quarantine_subject(
            ledger_db,
            subject_type="referral",
            subject_key="ref-1",
            hold_event_id=_hold_fact(ledger_db, "ref-1"),
            candidates=(PERSON_A,),
        )

    assert raised.value.review_id == queued.review_id
    assert count_pending(ledger_db) == 1


def test_a_subject_can_be_quarantined_again_after_a_resolution(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db)
    resolve_review(
        ledger_db,
        queued.review_id,
        reviewer_role=REVIEWER_ROLE,
        resolution_event_id=_declare_resolution(ledger_db),
    )

    again = quarantine_subject(
        ledger_db,
        subject_type="referral",
        subject_key="ref-1",
        hold_event_id=_hold_fact(ledger_db, "ref-1"),
        candidates=(PERSON_A,),
    )

    assert again.review_id != queued.review_id
    assert count_pending(ledger_db) == 1


def test_quarantining_against_an_undeclared_hold_is_refused(ledger_db: psycopg.Connection) -> None:
    _received(ledger_db, "ref-1")

    with pytest.raises(UnknownEventError):
        quarantine_subject(
            ledger_db,
            subject_type="referral",
            subject_key="ref-1",
            hold_event_id=uuid.uuid4(),
            candidates=(PERSON_A,),
        )


def test_a_candidate_set_carries_person_keys_only(ledger_db: psycopg.Connection) -> None:
    """Demographics are what a candidate set is tempting to carry, and must never reach the ledger."""
    _received(ledger_db, "ref-1")
    hold = _hold_fact(ledger_db, "ref-1")

    with pytest.raises(NonKeyCandidateError):
        quarantine_subject(
            ledger_db,
            subject_type="referral",
            subject_key="ref-1",
            hold_event_id=hold,
            candidates=[{"person_key": PERSON_A, "birth_date": "1970-01-01"}],  # type: ignore[list-item]
        )


def test_an_unknown_subject_type_is_refused(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(IllegalTransitionError):
        quarantine_subject(
            ledger_db,
            subject_type="patient",
            subject_key="p-1",
            hold_event_id=uuid.uuid4(),
        )


# --- the listing ------------------------------------------------------------------------------


def test_the_queue_lists_oldest_first_and_filters_by_subject_type(ledger_db: psycopg.Connection) -> None:
    first = _quarantine(ledger_db, "ref-1")
    second = _quarantine(ledger_db, "ref-2")

    assert [item.review_id for item in list_review_queue(ledger_db, subject_type="referral")] == [
        first.review_id,
        second.review_id,
    ]
    assert list_review_queue(ledger_db, subject_type="enrollment") == []
    assert [item.review_id for item in list_review_queue(ledger_db, limit=1)] == [first.review_id]
    assert count_pending(ledger_db, subject_type="referral") == 2
    assert count_pending(ledger_db, subject_type="enrollment") == 0


def test_the_queue_can_be_listed_without_candidates(ledger_db: psycopg.Connection) -> None:
    queued = _quarantine(ledger_db, "ref-1", candidates=())

    assert queued.candidates == ()
    assert list_review_queue(ledger_db)[0].candidates == ()
