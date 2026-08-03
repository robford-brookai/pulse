"""The canonical fold — the one ordering rule the ledger, the reads, and the warehouse share.

These tests are pure: no store, no clock. They pin the three things a second implementation
(task 5.1's independent re-derivation, the warehouse's `STG_EVENTS` fold) has to agree on —
the sort key, what a reversal removes, and what an empty history folds to.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pulse_ledger.fold import FoldedEvent, fold_state, surviving_events

BASE = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _event(
    *,
    to_state: str,
    effective_at: datetime,
    recorded_at: datetime | None = None,
    event_id: uuid.UUID | None = None,
    reverses_event_id: uuid.UUID | None = None,
) -> FoldedEvent:
    return FoldedEvent(
        event_id=event_id or uuid.uuid4(),
        to_state=to_state,
        effective_at=effective_at,
        recorded_at=recorded_at or effective_at,
        reverses_event_id=reverses_event_id,
    )


def test_empty_history_folds_to_nothing() -> None:
    assert fold_state([]) is None


def test_fold_orders_by_effective_at_not_input_order() -> None:
    later = _event(to_state="resolved", effective_at=BASE + timedelta(days=1))
    earlier = _event(to_state="received", effective_at=BASE)
    folded = fold_state([later, earlier])
    assert folded is not None
    assert folded.state == "resolved"
    # And the reverse input order gives the same answer: order comes from the data.
    assert fold_state([earlier, later]) == folded


def test_effective_at_ties_break_by_recorded_at() -> None:
    first_learned = _event(to_state="resolved", effective_at=BASE, recorded_at=BASE + timedelta(hours=1))
    last_learned = _event(to_state="closed", effective_at=BASE, recorded_at=BASE + timedelta(hours=2))
    folded = fold_state([last_learned, first_learned])
    assert folded is not None
    assert folded.state == "closed"
    assert folded.event_id == last_learned.event_id


def test_a_backdated_event_does_not_become_the_current_state() -> None:
    forward = _event(to_state="resolved", effective_at=BASE + timedelta(days=2), recorded_at=BASE)
    backdated = _event(
        to_state="received",
        effective_at=BASE,
        recorded_at=BASE + timedelta(days=5),  # learned last, true first
    )
    folded = fold_state([forward, backdated])
    assert folded is not None
    assert folded.state == "resolved"
    assert folded.effective_at == forward.effective_at


def test_a_reversal_removes_both_itself_and_the_event_it_voids() -> None:
    genesis = _event(to_state="received", effective_at=BASE)
    mistake = _event(to_state="closed", effective_at=BASE + timedelta(days=1))
    reversal = _event(
        to_state="closed",
        effective_at=mistake.effective_at,
        recorded_at=BASE + timedelta(days=2),
        reverses_event_id=mistake.event_id,
    )
    history = [genesis, mistake, reversal]

    assert [event.event_id for event in surviving_events(history)] == [genesis.event_id]
    folded = fold_state(history)
    assert folded is not None
    assert folded.state == "received"
    assert folded.event_id == genesis.event_id


def test_reversing_the_only_event_folds_to_nothing() -> None:
    genesis = _event(to_state="received", effective_at=BASE)
    reversal = _event(
        to_state="received",
        effective_at=BASE,
        recorded_at=BASE + timedelta(days=1),
        reverses_event_id=genesis.event_id,
    )
    assert fold_state([genesis, reversal]) is None


def test_a_reversal_does_not_void_events_it_does_not_reference() -> None:
    genesis = _event(to_state="received", effective_at=BASE)
    kept = _event(to_state="resolved", effective_at=BASE + timedelta(days=1))
    mistake = _event(to_state="closed", effective_at=BASE + timedelta(days=2))
    reversal = _event(
        to_state="closed",
        effective_at=mistake.effective_at,
        recorded_at=BASE + timedelta(days=3),
        reverses_event_id=mistake.event_id,
    )
    folded = fold_state([genesis, kept, mistake, reversal])
    assert folded is not None
    assert folded.state == "resolved"
