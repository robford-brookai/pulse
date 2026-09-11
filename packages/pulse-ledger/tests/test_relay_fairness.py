"""Task 1.1 — the candidate-subject scan and its reusable scheduling state.

The old selection query (`pending_rows`, `ORDER BY subject_type, subject_key, seq LIMIT
batch_size`) reads whichever subjects sort first, so one subject with a backlog bigger than the
batch size fills every pass and a later-sorting subject with due work is never even read — no lock,
no backoff involved, just alphabetical bad luck. This file reproduces that starvation first, then
exercises the scan this task introduces to fix it: a finite candidate-subject set, walked by an
explicit cursor (`ScanState`) that a caller keeps and passes back in, advancing a bounded number of
subjects per pass, past locked and backing-off heads alike, wrapping at the end of the set.

Wiring this scan into `relay_once`'s selection is task 1.2 — nothing here changes what
`relay_once` publishes.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from pulse_ledger import relay as relay_module
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.relay import ScanState, candidate_subjects, pending_rows, scan_pass

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

REFERRAL_STATES = ("received", "resolved", "screened")


def _declare(subject_key: str, to_state: str, effective_at: datetime) -> Declaration:
    return Declaration(
        subject_type="referral",
        subject_key=subject_key,
        event_type=f"referral.{to_state}",
        to_state=to_state,
        effective_at=effective_at,
        actor_type="system",
        actor_id="relay-fairness-tests",
        producer="pulse-ledger-tests",
        payload={"note": "synthetic"},
    )


def _commit_history(conn: psycopg.Connection, subject_key: str, count: int = 3) -> list[uuid.UUID]:
    """Commit `count` legal forward events for one subject and return their ids in order."""
    ids = []
    for index in range(min(count, len(REFERRAL_STATES))):
        result = commit_declaration(conn, _declare(subject_key, REFERRAL_STATES[index], T0 + timedelta(hours=index)))
        ids.append(result.event_id)
    return ids


def _commit_one(conn: psycopg.Connection, subject_key: str, *, state: str = "received") -> uuid.UUID:
    return commit_declaration(conn, _declare(subject_key, state, T0)).event_id


def _back_off(conn: psycopg.Connection, event_id: uuid.UUID, *, until: datetime) -> None:
    """Put one row into a backoff window, as `_record_failure` would after a transient failure."""
    conn.execute(
        "UPDATE ledger.outbox SET attempts = 1, next_attempt_at = %s WHERE event_id = %s",
        (until, event_id),
    )


# --- 1. Reproduce the starvation the old LIMIT query has ---------------------------------------


def test_a_big_early_backlog_starves_a_due_late_subject_under_the_old_limit(
    ledger_db: psycopg.Connection,
) -> None:
    """`ref-aaa` sorts first and has more rows than the batch; `ref-zzz` never gets read."""
    _commit_history(ledger_db, "ref-aaa", count=3)
    _commit_one(ledger_db, "ref-zzz")

    rows = pending_rows(ledger_db, batch_size=3)

    subject_keys = {row.subject_key for row in rows}
    assert subject_keys == {"ref-aaa"}, "the old LIMIT query reads only the early-sorting backlog"
    assert "ref-zzz" not in subject_keys, "a due, independent subject is starved by sort order alone"


# --- 2. The finite candidate set -----------------------------------------------------------------


def test_candidate_subjects_is_the_finite_set_with_pending_work(ledger_db: psycopg.Connection) -> None:
    _commit_one(ledger_db, "ref-a")
    _commit_one(ledger_db, "ref-b")
    [done_id] = _commit_history(ledger_db, "ref-done", count=1)
    ledger_db.execute("UPDATE ledger.outbox SET published_at = now() WHERE event_id = %s", (done_id,))

    subjects = candidate_subjects(ledger_db)

    assert subjects == [("referral", "ref-a"), ("referral", "ref-b")]


# --- 3. Bounded per-pass examination ---------------------------------------------------------------


def test_a_pass_examines_at_most_the_budget(ledger_db: psycopg.Connection) -> None:
    for key in ("ref-1", "ref-2", "ref-3", "ref-4"):
        _commit_one(ledger_db, key)
    subjects = candidate_subjects(ledger_db)
    assert len(subjects) == 4

    result = scan_pass(ledger_db, subjects, ScanState(), budget=2, now=T0)

    assert len(result.examined) == 2


# --- 4. Advancing across backed-off and locked subjects, without stalling ------------------------


def test_the_scan_advances_past_a_backing_off_head_without_stalling(ledger_db: psycopg.Connection) -> None:
    [stuck_id] = _commit_history(ledger_db, "ref-stuck", count=1)
    _back_off(ledger_db, stuck_id, until=T0 + timedelta(minutes=5))
    _commit_one(ledger_db, "ref-ready")
    subjects = candidate_subjects(ledger_db)
    assert subjects == [("referral", "ref-ready"), ("referral", "ref-stuck")]

    result = scan_pass(ledger_db, subjects, ScanState(), budget=2, now=T0)

    statuses = {status.subject[1]: status for status in result.examined}
    assert statuses["ref-ready"].eligible is True
    assert statuses["ref-stuck"].eligible is False
    assert statuses["ref-stuck"].reason == "backing_off"
    # the cursor moved past the backing-off subject rather than getting stuck on it
    assert result.state.cursor == ("referral", "ref-stuck")


def test_the_scan_advances_past_a_locked_subject_without_stalling(
    ledger_db: psycopg.Connection, pg_database: dict
) -> None:
    _commit_one(ledger_db, "ref-locked")
    _commit_one(ledger_db, "ref-free")
    subjects = candidate_subjects(ledger_db)
    key = "referral\x1fref-locked"

    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as other:
        held = other.execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (relay_module._RELAY_LOCK_NAMESPACE, key)
        ).fetchone()
        assert held is not None and held[0] is True

        result = scan_pass(ledger_db, subjects, ScanState(), budget=2, now=T0)

    statuses = {status.subject[1]: status for status in result.examined}
    assert statuses["ref-locked"].eligible is False
    assert statuses["ref-locked"].reason == "locked"
    assert statuses["ref-free"].eligible is True
    # a probe never keeps the lock — the relay's own later acquisition (task 1.2) is unaffected
    still_free = ledger_db.execute(
        "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (relay_module._RELAY_LOCK_NAMESPACE, "referral\x1fref-free")
    ).fetchone()
    assert still_free is not None and still_free[0] is True
    ledger_db.execute(
        "SELECT pg_advisory_unlock(%s, hashtext(%s))", (relay_module._RELAY_LOCK_NAMESPACE, "referral\x1fref-free")
    )


# --- 5. Wrapping at the end of the candidate set --------------------------------------------------


def test_the_scan_wraps_to_the_front_of_the_candidate_set(ledger_db: psycopg.Connection) -> None:
    for key in ("ref-1", "ref-2", "ref-3"):
        _commit_one(ledger_db, key)
    subjects = candidate_subjects(ledger_db)
    assert len(subjects) == 3

    first = scan_pass(ledger_db, subjects, ScanState(), budget=2, now=T0)
    assert [status.subject for status in first.examined] == [subjects[0], subjects[1]]

    second = scan_pass(ledger_db, subjects, first.state, budget=2, now=T0)
    # only one subject left before the end, then the scan wraps back to the front
    assert [status.subject for status in second.examined] == [subjects[2], subjects[0]]


# --- 6. Finite-set scan-cycle progress with a reusable, bounded scheduling state ------------------


def test_a_complete_scan_cycle_visits_every_candidate_within_the_bound(ledger_db: psycopg.Connection) -> None:
    """A worker running successive bounded passes, with no change to the candidate set, visits the
    whole finite set within `ceil(N / B)` passes — the bound the fairness scenario is stated over."""
    n, budget = 7, 3
    for index in range(n):
        _commit_one(ledger_db, f"ref-{index:02d}")
    subjects = candidate_subjects(ledger_db)
    assert len(subjects) == n

    state = ScanState()
    seen: set[tuple[str, str]] = set()
    passes = 0
    expected_passes = math.ceil(n / budget)
    for _ in range(expected_passes):
        result = scan_pass(ledger_db, subjects, state, budget=budget, now=T0)
        assert len(result.examined) <= budget, "a pass never examines more than its budget"
        seen.update(status.subject for status in result.examined)
        state = result.state
        passes += 1

    assert seen == set(subjects), f"the full candidate set was not visited within {expected_passes} passes"
    assert passes == expected_passes
