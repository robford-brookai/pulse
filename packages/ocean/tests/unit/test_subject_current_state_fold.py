"""SUBJECT_CURRENT_STATE fold — fixture-driven, over a small landed-events table (reconciliation-
sweeps task 1.2).

`subject_current_state.sql` cannot be executed offline (no live Snowflake in `task check`,
docs/contracts/consumes.md posture), so this test carries a small pure-Python restatement of the
view's own algorithm — "latest landed event per `(subject_type, subject_key)` by `seq`, floored
below by `_loaded_at >= min_complete_from`" — and drives it over a synthetic landed-events table,
the offline stand-in `test_stg_events_sql.py` already establishes for this SQL file's shape. Any
future divergence between this restatement and the committed SQL is caught by
`test_subject_current_state_sql.py`'s text assertions on the same predicates.

Synthetic data only, no PHI (repo-wide posture): subject keys and states below are fixtures.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

_MIN_COMPLETE_FROM = datetime(2026, 8, 26, tzinfo=UTC)


@dataclass(frozen=True)
class _LandedRow:
    """One synthetic row of the raw landing this view folds — the shape
    `subject_current_state.sql` reads off `STG_EVENTS.EVENTS`."""

    subject_type: str
    subject_key: str
    seq: int
    to_state: str | None
    loaded_at: datetime


@dataclass(frozen=True)
class _FoldedRow:
    """One folded row — the shape this view's `SELECT` list produces."""

    subject_type: str
    subject_key: str
    seq: int
    state: str | None
    loaded_at: datetime

    def as_landing_reader_row(self) -> dict[str, object]:
        """The keys `schedules.sweep_readers.LandingReader` reads a raw row for (task 1.3):
        `subject_key`, `state`, `seq`."""
        return {"subject_key": self.subject_key, "state": self.state, "seq": self.seq}


def _fold_subject_current_state(landed_events: Sequence[_LandedRow]) -> list[_FoldedRow]:
    """Restates `subject_current_state.sql`: floor on `_loaded_at`, then latest by `seq` per
    `(subject_type, subject_key)`, `state` from `payload.to_state` (`None` when absent)."""
    above_floor = [row for row in landed_events if row.loaded_at >= _MIN_COMPLETE_FROM]
    winners: dict[tuple[str, str], _LandedRow] = {}
    for row in above_floor:
        key = (row.subject_type, row.subject_key)
        current = winners.get(key)
        if current is None or row.seq > current.seq:
            winners[key] = row
    return [
        _FoldedRow(
            subject_type=row.subject_type,
            subject_key=row.subject_key,
            seq=row.seq,
            state=row.to_state,
            loaded_at=row.loaded_at,
        )
        for row in winners.values()
    ]


def _landed_row(
    *, subject_type: str, subject_key: str, seq: int, loaded_at: datetime, to_state: str | None
) -> _LandedRow:
    return _LandedRow(
        subject_type=subject_type, subject_key=subject_key, seq=seq, to_state=to_state, loaded_at=loaded_at
    )


def test_latest_by_seq_wins_per_subject() -> None:
    landed = [
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=1,
            loaded_at=datetime(2026, 8, 27, tzinfo=UTC),
            to_state="pending",
        ),
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=3,
            loaded_at=datetime(2026, 8, 28, tzinfo=UTC),
            to_state="active",
        ),
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=2,
            loaded_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
            to_state="verified",
        ),
    ]
    folded = _fold_subject_current_state(landed)
    assert len(folded) == 1
    assert folded[0] == _FoldedRow(
        subject_type="enrollment",
        subject_key="enr-1",
        seq=3,
        state="active",
        loaded_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


def test_each_subject_folds_independently() -> None:
    landed = [
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=5,
            loaded_at=datetime(2026, 8, 27, tzinfo=UTC),
            to_state="active",
        ),
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-2",
            seq=1,
            loaded_at=datetime(2026, 8, 27, tzinfo=UTC),
            to_state="pending",
        ),
    ]
    folded = {(row.subject_type, row.subject_key): row for row in _fold_subject_current_state(landed)}
    assert folded[("enrollment", "enr-1")].state == "active"
    assert folded[("enrollment", "enr-2")].state == "pending"


def test_rows_before_the_floor_are_excluded_entirely() -> None:
    landed = [
        _landed_row(
            subject_type="enrollment",
            subject_key="pre-floor-subject",
            seq=1,
            loaded_at=datetime(2026, 8, 25, tzinfo=UTC),
            to_state="active",
        ),
    ]
    assert _fold_subject_current_state(landed) == []


def test_a_subject_landed_on_both_sides_of_the_floor_keeps_only_its_post_floor_events() -> None:
    landed = [
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=1,
            loaded_at=datetime(2026, 8, 24, tzinfo=UTC),
            to_state="pending",
        ),
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=2,
            loaded_at=datetime(2026, 8, 26, tzinfo=UTC),
            to_state="active",
        ),
    ]
    folded = _fold_subject_current_state(landed)
    assert len(folded) == 1
    assert folded[0].seq == 2
    assert folded[0].state == "active"


def test_a_non_state_bearing_winner_folds_to_no_state() -> None:
    """The winning row by `seq` may carry no `to_state` (e.g. a reversal-only event) — this view
    does not reach past it for a state-bearing predecessor (SQL header comment); the sweep reads
    the resulting `None` as a `state` divergence like any other disagreement."""
    landed = [
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=1,
            loaded_at=datetime(2026, 8, 27, tzinfo=UTC),
            to_state="active",
        ),
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=2,
            loaded_at=datetime(2026, 8, 27, tzinfo=UTC),
            to_state=None,
        ),
    ]
    folded = _fold_subject_current_state(landed)
    assert len(folded) == 1
    assert folded[0].seq == 2
    assert folded[0].state is None


def test_folded_shape_matches_the_landing_readers_row_contract() -> None:
    """`schedules.sweep_readers.LandingReader` reads raw rows keyed `subject_key`/`state`/`seq`
    (task 1.3) — this fold's output must carry those same keys so a live adapter over this view
    needs no reshaping beyond column selection."""
    landed = [
        _landed_row(
            subject_type="enrollment",
            subject_key="enr-1",
            seq=1,
            loaded_at=datetime(2026, 8, 27, tzinfo=UTC),
            to_state="active",
        ),
    ]
    folded = _fold_subject_current_state(landed)[0]
    assert {"subject_key", "state", "seq"} <= folded.as_landing_reader_row().keys()
