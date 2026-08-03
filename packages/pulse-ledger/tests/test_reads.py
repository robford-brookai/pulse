"""Current-state enumeration — task 4.1's month-open case, against a real Postgres.

The spec scenario is one query: enrollments in `active`, `on_hold` and `ended` exist, month-open
asks for `active` or `on_hold`, and exactly those come back. What the rest of this suite protects is
the "consistent with the ledger's own state rows at read time" half of the requirement — the
enumeration follows a reversal and a backdated declaration because it reads `current_state`, which
the commit path re-folds in the same transaction as the event.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_ledger.commit import Declaration, commit_declaration, commit_reversal
from pulse_ledger.reads import NegativeLimitError, count_by_state, enumerate_state
from pulse_ledger.validation import IllegalTransitionError

SERVICE_ROLE = "pulse_ledger_service"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _declare(
    subject_type: str = "enrollment",
    subject_key: str = "enr-1",
    to_state: str = "pending_start",
    effective_at: datetime | None = None,
    **overrides: Any,
) -> Declaration:
    fields: dict[str, Any] = {
        "subject_type": subject_type,
        "subject_key": subject_key,
        "event_type": f"{subject_type}.{to_state}",
        "to_state": to_state,
        "effective_at": effective_at or T0,
        "actor_type": "system",
        "actor_id": "scheduler",
        "producer": "pulse-ledger-tests",
    }
    fields.update(overrides)
    return Declaration(**fields)


def _enrol(conn: psycopg.Connection, subject_key: str, *states: str) -> list[Any]:
    """Walk one enrollment through `states` from genesis, one declaration per step."""
    results = []
    for step, state in enumerate(states):
        results.append(
            commit_declaration(
                conn, _declare(subject_key=subject_key, to_state=state, effective_at=T0 + timedelta(days=step))
            )
        )
    return results


# --- the spec scenario: month-open enumerates from the ledger ---------------------------------


def test_month_open_enumerates_exactly_the_active_and_on_hold_enrollments(ledger_db: psycopg.Connection) -> None:
    _enrol(ledger_db, "enr-active", "pending_start", "active")
    _enrol(ledger_db, "enr-held", "pending_start", "active", "on_hold")
    _enrol(ledger_db, "enr-ended", "pending_start", "active", "ended")

    billable = enumerate_state(ledger_db, "enrollment", ["active", "on_hold"])

    assert [(row.subject_key, row.state) for row in billable] == [
        ("enr-active", "active"),
        ("enr-held", "on_hold"),
    ]


def test_enumeration_reflects_the_ledger_state_row_not_a_stale_read(ledger_db: psycopg.Connection) -> None:
    """A reversal re-folds `current_state`, so the next enumeration sees the re-folded state."""
    *_, ended = _enrol(ledger_db, "enr-1", "pending_start", "active", "ended")
    assert [row.state for row in enumerate_state(ledger_db, "enrollment", ["ended"])] == ["ended"]

    commit_reversal(
        ledger_db,
        reverses_event_id=ended.event_id,
        actor_type="human",
        actor_id="ops",
        producer="pulse-ledger-tests",
        reason="ended in error",
    )

    assert enumerate_state(ledger_db, "enrollment", ["ended"]) == []
    assert [row.subject_key for row in enumerate_state(ledger_db, "enrollment", ["active"])] == ["enr-1"]


def test_a_backdated_declaration_does_not_move_the_enumeration(ledger_db: psycopg.Connection) -> None:
    _enrol(ledger_db, "enr-1", "pending_start", "active")
    # True after genesis but before the activation, and learned last: it departs from
    # `pending_start`, which is what makes it legal, and lands mid-history.
    commit_declaration(
        ledger_db,
        _declare(to_state="ended", effective_at=T0 + timedelta(hours=12)),
    )

    # The backdated fact joins history before `active`, so `active` is still the current state.
    assert [row.state for row in enumerate_state(ledger_db, "enrollment", ["active", "ended"])] == ["active"]


def test_enumeration_carries_the_event_the_state_was_folded_from(ledger_db: psycopg.Connection) -> None:
    _, activated = _enrol(ledger_db, "enr-1", "pending_start", "active")

    (row,) = enumerate_state(ledger_db, "enrollment", ["active"])

    assert row.last_event_id == activated.event_id
    assert row.effective_at == T0 + timedelta(days=1)
    assert row.subject_type == "enrollment"


# --- filters, ordering, paging ---------------------------------------------------------------


def test_no_state_filter_enumerates_every_state_of_the_type(ledger_db: psycopg.Connection) -> None:
    _enrol(ledger_db, "enr-1", "pending_start", "active")
    _enrol(ledger_db, "enr-2", "pending_start", "active", "ended")
    commit_declaration(ledger_db, _declare(subject_type="referral", subject_key="ref-1", to_state="received"))

    rows = enumerate_state(ledger_db, "enrollment")

    assert [(row.subject_key, row.state) for row in rows] == [("enr-1", "active"), ("enr-2", "ended")]


def test_an_empty_state_filter_is_no_subjects_not_every_subject(ledger_db: psycopg.Connection) -> None:
    _enrol(ledger_db, "enr-1", "pending_start", "active")

    assert enumerate_state(ledger_db, "enrollment", []) == []


def test_paging_by_subject_key_walks_the_enumeration_without_repeats(ledger_db: psycopg.Connection) -> None:
    for index in range(5):
        _enrol(ledger_db, f"enr-{index}", "pending_start", "active")

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = enumerate_state(ledger_db, "enrollment", ["active"], after_subject_key=cursor, limit=2)
        if not page:
            break
        seen.extend(row.subject_key for row in page)
        cursor = page[-1].subject_key

    assert seen == [f"enr-{index}" for index in range(5)]


def test_a_negative_limit_is_a_caller_error(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(NegativeLimitError):
        enumerate_state(ledger_db, "enrollment", ["active"], limit=-1)


# --- the catalog is the floor under the read path ---------------------------------------------


def test_an_unknown_state_is_rejected_rather_than_answered_as_empty(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(IllegalTransitionError) as raised:
        enumerate_state(ledger_db, "enrollment", ["active", "on_hold_typo"])

    assert "on_hold_typo" in raised.value.reason
    assert raised.value.catalog_version


def test_an_unknown_subject_type_is_rejected(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(IllegalTransitionError) as raised:
        enumerate_state(ledger_db, "patient", ["active"])

    assert "patient" in raised.value.reason


# --- counts and the read-only posture ---------------------------------------------------------


def test_count_by_state_reports_every_catalog_state_including_the_empty_ones(ledger_db: psycopg.Connection) -> None:
    _enrol(ledger_db, "enr-1", "pending_start", "active")
    _enrol(ledger_db, "enr-2", "pending_start", "active")
    _enrol(ledger_db, "enr-3", "pending_start", "active", "on_hold")

    assert count_by_state(ledger_db, "enrollment") == {
        "pending_start": 0,
        "active": 2,
        "on_hold": 1,
        "ended": 0,
    }


def test_the_service_role_can_enumerate(ledger_db: psycopg.Connection) -> None:
    _enrol(ledger_db, "enr-1", "pending_start", "active")

    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    try:
        assert [row.subject_key for row in enumerate_state(ledger_db, "enrollment", ["active"])] == ["enr-1"]
    finally:
        ledger_db.execute("RESET ROLE")
