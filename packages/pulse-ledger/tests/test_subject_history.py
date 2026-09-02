"""Per-subject committed history, read from the ledger in ledger sequence (design decision 5).

The property under test is not "some events come back" — it is that the sequence a rebuild replays
is the sequence live apply saw, which is the outbox `seq` the relay publishes in. So: `seq` order
even for a backdated event, reversals and reversed events *present* (history is history; the fold
drops them, the read does not), the relay's envelope shape verbatim, one subject and no other, and
an unknown subject answering with an empty history rather than an error.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_ledger.commit import Declaration, commit_declaration, commit_reversal
from pulse_ledger.reads import UnrelayedEventError, subject_history
from pulse_ledger.validation import IllegalTransitionError

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _declare(
    subject_key: str = "enr-1",
    to_state: str = "pending_start",
    effective_at: datetime | None = None,
    **overrides: Any,
) -> Declaration:
    fields: dict[str, Any] = {
        "subject_type": "enrollment",
        "subject_key": subject_key,
        "event_type": f"enrollment.{to_state}",
        "to_state": to_state,
        "effective_at": effective_at or T0,
        "actor_type": "system",
        "actor_id": "scheduler",
        "producer": "pulse-ledger-tests",
    }
    fields.update(overrides)
    return Declaration(**fields)


def _walk(conn: psycopg.Connection, subject_key: str, *states: str) -> list[Any]:
    return [
        commit_declaration(conn, _declare(subject_key=subject_key, to_state=state, effective_at=T0 + timedelta(days=i)))
        for i, state in enumerate(states)
    ]


# --- the sequence itself ----------------------------------------------------------------------


def test_history_returns_the_subjects_events_in_fold_order(ledger_db: psycopg.Connection) -> None:
    _walk(ledger_db, "enr-1", "pending_start", "active", "on_hold")

    history = subject_history(ledger_db, "enrollment", "enr-1")

    assert [event["payload"]["to_state"] for event in history] == ["pending_start", "active", "on_hold"]
    assert [event["seq"] for event in history] == [1, 2, 3]


def test_a_backdated_event_replays_where_it_arrived_not_where_it_belongs(ledger_db: psycopg.Connection) -> None:
    """Ledger sequence is arrival order. A live consumer saw the backdated event last, watermarked
    on its `seq`, and a replay that reordered it would disagree with incremental apply — the one
    disagreement a rebuild drill exists to rule out. The bitemporal order is the *fold's*, and
    `pulse_ledger.fold` owns it."""
    _walk(ledger_db, "enr-1", "pending_start", "active", "on_hold")
    commit_declaration(
        ledger_db,
        _declare(subject_key="enr-1", to_state="ended", effective_at=T0 + timedelta(days=1, hours=12)),
    )

    history = subject_history(ledger_db, "enrollment", "enr-1")

    assert [event["seq"] for event in history] == [1, 2, 3, 4]
    assert [event["payload"]["to_state"] for event in history] == ["pending_start", "active", "on_hold", "ended"]
    assert history[-1]["effective_at"] < history[-2]["effective_at"]


def test_history_keeps_a_reversal_and_the_event_it_reverses(ledger_db: psycopg.Connection) -> None:
    """A fold drops both; a *history* read that dropped them would hide the correction itself."""
    _, active = _walk(ledger_db, "enr-1", "pending_start", "active")
    commit_reversal(
        ledger_db,
        reverses_event_id=active.event_id,
        actor_type="system",
        actor_id="scheduler",
        producer="pulse-ledger-tests",
        reason="mistaken activation",
    )

    history = subject_history(ledger_db, "enrollment", "enr-1")

    assert len(history) == 3
    reversal = history[-1]
    assert reversal["reverses_event_id"] == str(active.event_id)


# --- scope: this subject, nothing more ---------------------------------------------------------


def test_history_holds_one_subject_only(ledger_db: psycopg.Connection) -> None:
    _walk(ledger_db, "enr-1", "pending_start", "active")
    _walk(ledger_db, "enr-2", "pending_start", "active", "ended")

    history = subject_history(ledger_db, "enrollment", "enr-1")

    assert {event["subject_key"] for event in history} == {"enr-1"}
    assert len(history) == 2


def test_an_unknown_subject_has_an_empty_history(ledger_db: psycopg.Connection) -> None:
    _walk(ledger_db, "enr-1", "pending_start")

    assert subject_history(ledger_db, "enrollment", "enr-nobody") == []


def test_an_unknown_subject_type_is_rejected_not_answered_empty(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(IllegalTransitionError):
        subject_history(ledger_db, "enrolment", "enr-1")


# --- paging ------------------------------------------------------------------------------------


def test_after_seq_and_limit_page_the_history_without_gaps(ledger_db: psycopg.Connection) -> None:
    _walk(ledger_db, "enr-1", "pending_start", "active", "on_hold", "active")

    first = subject_history(ledger_db, "enrollment", "enr-1", limit=2)
    second = subject_history(ledger_db, "enrollment", "enr-1", after_seq=first[-1]["seq"], limit=2)

    assert [event["seq"] for event in first] == [1, 2]
    assert [event["seq"] for event in second] == [3, 4]


def test_a_negative_limit_is_a_callers_arithmetic_error(ledger_db: psycopg.Connection) -> None:
    from pulse_ledger.reads import NegativeLimitError

    with pytest.raises(NegativeLimitError):
        subject_history(ledger_db, "enrollment", "enr-1", limit=-1)


# --- envelope shape --------------------------------------------------------------------------


def test_the_envelope_is_the_one_the_relay_publishes(ledger_db: psycopg.Connection) -> None:
    """Same shape or the rebuild folds something the live consumer never saw."""
    from pulse_ledger.relay import pending_rows

    _walk(ledger_db, "enr-1", "pending_start", "active")

    published = {row.event_id: row.envelope for row in pending_rows(ledger_db)}
    for event in subject_history(ledger_db, "enrollment", "enr-1"):
        assert event == published[uuid.UUID(event["event_id"])]


# --- the loud failure ------------------------------------------------------------------------


def test_an_event_with_no_outbox_row_fails_loudly(ledger_db: psycopg.Connection) -> None:
    """`seq` comes from the outbox row every commit writes. A missing one is a torn history, and a
    torn history folded silently is a projection rebuilt to the wrong state."""
    (first,) = _walk(ledger_db, "enr-1", "pending_start")
    ledger_db.execute("DELETE FROM ledger.outbox WHERE event_id = %s", (first.event_id,))

    with pytest.raises(UnrelayedEventError) as excinfo:
        subject_history(ledger_db, "enrollment", "enr-1")
    assert str(first.event_id) in str(excinfo.value)
