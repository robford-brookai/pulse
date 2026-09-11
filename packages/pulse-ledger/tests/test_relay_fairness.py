"""Task 1.1 — the candidate-subject scan and its reusable scheduling state — and task 1.2, wiring
that scan into publication with a per-subject row budget.

The old selection query (`pending_rows`, `ORDER BY subject_type, subject_key, seq LIMIT
batch_size`) reads whichever subjects sort first, so one subject with a backlog bigger than the
batch size fills every pass and a later-sorting subject with due work is never even read — no lock,
no backoff involved, just alphabetical bad luck. This file reproduces that starvation first, then
exercises the scan this task introduces to fix it: a finite candidate-subject set, walked by an
explicit cursor (`ScanState`) that a caller keeps and passes back in, advancing a bounded number of
subjects per pass, past locked and backing-off heads alike, wrapping at the end of the set.

Task 1.2 wires that scan into `relay_fair_pass`, which acquires each eligible subject's lock and
rereads its pending head fresh under it — never the scan's own probe snapshot, which releases the
lock immediately, and never a snapshot taken before any lock at all. The second half of this file
exercises that: the per-subject row budget bounding one pass's publication, and a pre-lock
snapshot never treated as current once another relay has published under the same subject.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from pulse_ledger import relay as relay_module
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.relay import (
    ScanState,
    candidate_subjects,
    pending_rows,
    relay_fair_pass,
    scan_pass,
)

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


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@dataclass
class FakePublisher:
    """A bus that always accepts and records what it published, in the order it arrived."""

    published: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
        self.published.append(event)

    def seqs_for(self, subject_key: str) -> list[int]:
        return [event["seq"] for event in self.published if event["subject_key"] == subject_key]


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


# --- 7. Task 1.2 — fair selection wired into publication, with a per-subject row budget ----------


def test_relay_fair_pass_publishes_the_starved_subject_the_old_limit_missed(
    ledger_db: psycopg.Connection,
) -> None:
    """The same skew as test 1, but through `relay_fair_pass`: `ref-zzz` is not starved."""
    _commit_history(ledger_db, "ref-aaa", count=3)
    _commit_one(ledger_db, "ref-zzz")
    publisher = FakePublisher()

    _result, state = _run(relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=1, row_budget=10, now=T0))
    assert publisher.seqs_for("ref-zzz") == [], "budget 1 examines ref-aaa first, in candidate order"

    _result, state = _run(relay_fair_pass(ledger_db, publisher, state, subject_budget=1, row_budget=10, now=T0))

    assert publisher.seqs_for("ref-zzz") == [1], "the second pass's cursor reached the starved subject"


def test_relay_fair_pass_bounds_rows_published_per_subject_to_the_row_budget(
    ledger_db: psycopg.Connection,
) -> None:
    _commit_history(ledger_db, "ref-many", count=3)
    publisher = FakePublisher()

    result, _state = _run(relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=1, row_budget=2, now=T0))

    assert publisher.seqs_for("ref-many") == [1, 2], "only the row budget's worth published this pass"
    assert result.published == 2

    # The remainder is still there, waiting for a later visit — nothing was lost, just deferred.
    remaining = pending_rows(ledger_db)
    assert [row.seq for row in remaining] == [3]


def test_relay_fair_pass_defers_a_locked_subject_without_publishing_its_rows(
    ledger_db: psycopg.Connection, pg_database: dict
) -> None:
    _commit_one(ledger_db, "ref-locked")
    key = "referral\x1fref-locked"

    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as other:
        held = other.execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (relay_module._RELAY_LOCK_NAMESPACE, key)
        ).fetchone()
        assert held is not None and held[0] is True

        publisher = FakePublisher()
        result, _state = _run(relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=1, now=T0))

    assert publisher.published == []
    assert result.deferred == 1


def test_relay_fair_pass_never_treats_a_pre_lock_snapshot_as_current(
    ledger_db: psycopg.Connection, pg_database: dict
) -> None:
    """The scenario named by the spec's 'Publication uses current state under subject ownership'
    requirement: two workers see the same subject as a candidate; one locks it, publishes its only
    row and releases; the other then acquires the lock its probe found free and must reread rather
    than act on what it saw before either lock was taken.
    """
    [event_id] = _commit_history(ledger_db, "ref-race", count=1)
    subjects = candidate_subjects(ledger_db)
    assert subjects == [("referral", "ref-race")]

    # Worker A: identifies the candidate, locks it, publishes, records the head, releases.
    publisher_a = FakePublisher()
    result_a, _state_a = _run(relay_fair_pass(ledger_db, publisher_a, ScanState(), subject_budget=1, now=T0))
    assert publisher_a.seqs_for("ref-race") == [1]
    assert result_a.published == 1

    # Worker B holds a pre-lock snapshot from before A published — the exact stale state decision 2
    # exists to guard against — and only now runs its own fair pass over the same candidate set.
    stale_snapshot = pending_rows(ledger_db)
    assert not any(row.event_id == event_id for row in stale_snapshot), "already published; not in a fresh read"

    publisher_b = FakePublisher()
    result_b, _state_b = _run(relay_fair_pass(ledger_db, publisher_b, ScanState(), subject_budget=1, now=T0))

    assert publisher_b.published == [], "worker B's reread under its own lock found nothing pending"
    assert result_b.published == 0


def test_relay_fair_pass_rereads_under_lock_even_when_the_scan_probe_saw_it_pending(
    ledger_db: psycopg.Connection,
) -> None:
    """Between `scan_pass`'s eligibility probe (which releases its lock) and the actual publish
    acquisition, another relay can complete the subject. `relay_fair_pass` must not publish from
    what the probe observed — only from what its own lock's reread finds.
    """
    [event_id] = _commit_history(ledger_db, "ref-between", count=1)

    # Simulate another relay completing the row between the probe and the real acquisition by
    # marking it published directly — the row a stale in-memory snapshot would still call pending.
    ledger_db.execute("UPDATE ledger.outbox SET published_at = now() WHERE event_id = %s", (event_id,))

    subjects = [("referral", "ref-between")]
    scan_result = scan_pass(ledger_db, subjects, ScanState(), budget=1, now=T0)
    assert scan_result.examined[0].eligible is True, "the probe ran before the row was marked published"

    publisher = FakePublisher()
    result, _state = _run(relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=1, now=T0))

    assert publisher.published == [], "the reread under lock found the row already published"
    assert result.published == 0


def test_relay_once_rereads_under_lock_too(ledger_db: psycopg.Connection) -> None:
    """`relay_once` keeps this task's fix as well: its own pre-lock grouping is a candidate list,
    never what gets published — a subject completed between that grouping and this call's lock
    acquisition publishes nothing twice.
    """
    from pulse_ledger.relay import relay_once

    [event_id] = _commit_history(ledger_db, "ref-once-race", count=1)
    ledger_db.execute("UPDATE ledger.outbox SET published_at = now() WHERE event_id = %s", (event_id,))

    publisher = FakePublisher()
    result = _run(relay_once(ledger_db, publisher, now=T0))

    assert publisher.published == []
    assert result.published == 0
