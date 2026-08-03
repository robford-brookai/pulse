"""The canonical fold: events → the state of one subject.

One ordering rule, stated once, so the three places that need it cannot disagree — the commit
path (which co-commits `current_state`), the read path, and the warehouse's independent
re-derivation. The rule:

1. Order by `effective_at`, ties by `recorded_at` (the bitemporal order of I10 — when the fact
   was true, then when the ledger learned it).
2. Drop every reversal event and every event a reversal references. A correction is a new
   append that voids a prior fact (I7); the voided fact stays readable in history but stops
   contributing to state.
3. The state is the last surviving event's `to_state`. No surviving events → no state, which is
   how a subject that does not exist yet is distinguished from one in an initial state.

`to_state` lives in the event's `payload` rather than in a column of its own: the `events` shape
is fixed by migration 0001 and the flat warehouse projection lists `payload` as parseable JSON.
`TO_STATE_KEY` names it in one place, so a later schema revision promoting it to a column has one
call site to change. An event whose payload carries no `to_state` is not state-bearing (the
`reconstruction_gap` vocabulary of task 3.5 is the case in point) and never enters a fold.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

#: Payload key carrying the state an event moves its subject into.
TO_STATE_KEY = "to_state"


def state_borne_by(payload: Mapping[str, object]) -> str | None:
    """The state this event moves its subject into, or `None` if it is not state-bearing."""
    value = payload.get(TO_STATE_KEY)
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class FoldedEvent:
    """The four fields a fold needs from a committed event."""

    event_id: uuid.UUID
    to_state: str
    effective_at: datetime
    recorded_at: datetime
    reverses_event_id: uuid.UUID | None = None


@dataclass(frozen=True)
class FoldedState:
    """The result of folding one subject's history."""

    state: str
    effective_at: datetime
    recorded_at: datetime
    event_id: uuid.UUID


def _sort_key(event: FoldedEvent) -> tuple[datetime, datetime]:
    return (event.effective_at, event.recorded_at)


def surviving_events(events: Iterable[FoldedEvent]) -> list[FoldedEvent]:
    """Events that still contribute to state, in fold order: no reversals, nothing reversed."""
    ordered = sorted(events, key=_sort_key)
    voided = {event.reverses_event_id for event in ordered if event.reverses_event_id is not None}
    return [event for event in ordered if event.reverses_event_id is None and event.event_id not in voided]


def fold_state(events: Iterable[FoldedEvent]) -> FoldedState | None:
    """Fold one subject's history to its current state, or `None` if nothing survives."""
    alive = surviving_events(events)
    if not alive:
        return None
    winner = alive[-1]
    return FoldedState(
        state=winner.to_state,
        effective_at=winner.effective_at,
        recorded_at=winner.recorded_at,
        event_id=winner.event_id,
    )


def state_as_of(events: Iterable[FoldedEvent], effective_at: datetime) -> FoldedState | None:
    """The state a subject was in at `effective_at` — the predecessor a new declaration departs from.

    A forward declaration departs from the latest state; a backdated one departs from the state
    that held when its fact was true. Both are this one query, because a new event's
    `recorded_at` is always later than every committed event's, so an existing event sharing
    `effective_at` is still a predecessor.
    """
    alive = [event for event in surviving_events(events) if event.effective_at <= effective_at]
    if not alive:
        return None
    winner = alive[-1]
    return FoldedState(
        state=winner.to_state,
        effective_at=winner.effective_at,
        recorded_at=winner.recorded_at,
        event_id=winner.event_id,
    )
