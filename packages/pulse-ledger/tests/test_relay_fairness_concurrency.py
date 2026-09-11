"""Task 2.1 — the retry, dead-letter and manual-redrive policy is unchanged by fair scheduling,
proved under the conditions that could have broken it.

`relay_fair_pass` (tasks 1.1/1.2) changed *which* subject a pass works and how much of it, not what
happens to a row that fails. The risk this file exists to close is that the new selection path has
its own copies of the delivery decisions — a subject picked by the scan is published through
`_relay_locked_subject`, not through `relay_once`'s grouping — so every guarantee the old path was
tested for has to hold on the new one too, and under concurrency rather than in a single pass.

Five conditions, each a scenario the spec states or a failure mode the fair pass introduces:

- **Two concurrent relays.** Two *real* Postgres connections to one database, so the advisory lock
  under test is the real one and not a mock of it. A subject one relay owns is deferred by the
  other, never published twice, and the second relay serves an independent subject meanwhile —
  including across the window the scan opens, where a subject free at probe time belongs to another
  relay by the time the pass reaches it.
- **Ambiguous publishes.** The bus accepted the entry and the ack was lost. The row redelivers with
  the same `event_id` and in `seq` order — at-least-once, deduplicable.
- **Worker restart.** Mid-publish (the worker dies holding an unmarked, already-delivered row) and
  between passes (ephemeral `ScanState` reset). Durable outbox state is what survives; scan
  position is not, and losing it costs only where the ring resumes.
- **Continuous hot-subject traffic.** A subject receiving new rows before every pass still does not
  consume the selection opportunities a cold, late-sorting subject is owed.
- **A backing-off head.** Later rows of its subject do not bypass it, and it does not monopolise the
  scan while it waits.

Scheduling here is controlled, never timed: interleavings are driven by `asyncio.Event` handshakes
inside a publisher that parks exactly where the test wants the other relay to run, and backoff
windows are crossed by passing a later `now`, not by sleeping. No test in this file waits on wall
clock, so none of it can flake on a slow machine.

Subjects are synthetic (`cov-*`, `ref-*`) and carry no PHI.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.relay import (
    MAX_ATTEMPTS,
    ScanState,
    candidate_subjects,
    dead_letter_depth,
    redrive,
    relay_fair_pass,
)

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

#: Legal forward referral path, one state per event (catalog: received → resolved → screened).
REFERRAL_STATES = ("received", "resolved", "screened")

#: `coverage` is the catalog's one cyclic subject (verified_active ↔ verified_inactive) and mints
#: implicitly, which is what lets a "hot" subject take an unbounded stream of legal events.
COVERAGE_FLIP = ("verified_active", "verified_inactive")


# --- Fixtures and helpers -----------------------------------------------------------------------


@pytest.fixture
def relay_b(ledger_db: psycopg.Connection, pg_database: dict[str, str]) -> Iterator[psycopg.Connection]:
    """A second, independent connection to the same database — the second relay.

    Depends on `ledger_db` so the schema exists, and is a separate session so its advisory locks
    are genuinely contended against the first relay's rather than re-entrantly granted.
    """
    with psycopg.connect(
        host=pg_database["host"],
        user=pg_database["user"],
        dbname=pg_database["dbname"],
        autocommit=True,
    ) as conn:
        yield conn


def _declare_referral(subject_key: str, to_state: str, effective_at: datetime) -> Declaration:
    return Declaration(
        subject_type="referral",
        subject_key=subject_key,
        event_type=f"referral.{to_state}",
        to_state=to_state,
        effective_at=effective_at,
        actor_type="system",
        actor_id="relay-fairness-concurrency-tests",
        producer="pulse-ledger-tests",
        payload={"note": "synthetic"},
    )


def _commit_referral(conn: psycopg.Connection, subject_key: str, count: int = 1) -> list[uuid.UUID]:
    """Commit `count` legal forward referral events for one subject, ids in `seq` order."""
    return [
        commit_declaration(
            conn, _declare_referral(subject_key, REFERRAL_STATES[index], T0 + timedelta(hours=index))
        ).event_id
        for index in range(count)
    ]


def _commit_coverage(conn: psycopg.Connection, subject_key: str, count: int, *, start: int = 0) -> list[uuid.UUID]:
    """Add `count` more events to a coverage subject, flipping between its two verified states."""
    return [
        commit_declaration(
            conn,
            Declaration(
                subject_type="coverage",
                subject_key=subject_key,
                event_type="declare_transition",
                to_state=COVERAGE_FLIP[(start + index) % len(COVERAGE_FLIP)],
                effective_at=T0 + timedelta(days=start + index),
                actor_type="system",
                actor_id="relay-fairness-concurrency-tests",
                producer="pulse-ledger-tests",
            ),
        ).event_id
        for index in range(count)
    ]


def _outbox(conn: psycopg.Connection, event_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT attempts, published_at, dead_lettered_at, next_attempt_at FROM ledger.outbox WHERE event_id = %s",
        (event_id,),
    ).fetchone()
    assert row is not None
    return dict(zip(("attempts", "published_at", "dead_lettered_at", "next_attempt_at"), row, strict=True))


class BusRefused(Exception):
    """What the fake bus raises, standing in for a transport rejection."""


@dataclass
class RecordingPublisher:
    """A bus that records what it accepted and refuses whatever `refuses` selects.

    `refuses` is a predicate over the envelope, so "this subject's `seq` 1 always fails" and "every
    entry fails" are both expressible without the test reaching into the relay.
    """

    refuses: Callable[[dict[str, Any]], bool] = lambda event: False
    published: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
        if self.refuses(event):
            raise BusRefused
        self.published.append(event)

    def seqs_for(self, subject_key: str) -> list[int]:
        return [event["seq"] for event in self.published if event["subject_key"] == subject_key]

    def event_ids(self) -> list[str]:
        return [event["event_id"] for event in self.published]


@dataclass
class ParkingPublisher:
    """A bus that parks inside `publish` until the test releases it.

    The entry is recorded *before* parking: at the moment the test is unblocked, the bus has the
    event and the relay has not yet marked the row — which is both where a second relay's
    contention is interesting and exactly what an ambiguous publish looks like from the outbox's
    side. Nothing here sleeps; `arrived`/`release` are the whole scheduler.
    """

    published: list[dict[str, Any]] = field(default_factory=list)
    arrived: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
        self.published.append(event)
        self.arrived.set()
        await self.release.wait()

    def seqs_for(self, subject_key: str) -> list[int]:
        return [event["seq"] for event in self.published if event["subject_key"] == subject_key]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- 1. Two concurrent relays, two real connections ----------------------------------------------


def test_a_subject_one_relay_owns_is_deferred_by_the_other_and_never_published_twice(
    ledger_db: psycopg.Connection, relay_b: psycopg.Connection
) -> None:
    """Spec: "Concurrent relays recheck completed rows".

    Relay A parks inside the publish, holding the subject's advisory lock on its own session.
    Relay B — a different Postgres connection, whose candidate snapshot was taken while the row
    was still pending — runs a complete pass against the same subject, then runs another after A
    has finished. Neither pass publishes: the first is locked out, the second rereads under its own
    lock and finds nothing pending.
    """
    [event_id] = _commit_referral(ledger_db, "ref-owned", count=1)
    assert ("referral", "ref-owned") in candidate_subjects(relay_b), "B sees the row as pending before A publishes"

    parking = ParkingPublisher()
    publisher_b = RecordingPublisher()

    async def scenario() -> None:
        worker_a = asyncio.create_task(relay_fair_pass(ledger_db, parking, ScanState(), subject_budget=4, now=T0))
        await parking.arrived.wait()  # A is inside the publish, holding the subject lock

        result_b, _ = await relay_fair_pass(relay_b, publisher_b, ScanState(), subject_budget=4, now=T0)
        assert publisher_b.published == [], "B must not publish a subject another relay owns"
        assert result_b.deferred == 1, "the locked subject is one deferred selection, not a row count"
        assert _outbox(ledger_db, event_id)["published_at"] is None, "A has not marked it yet"

        parking.release.set()
        result_a, _ = await worker_a
        assert result_a.published == 1

        result_b_again, _ = await relay_fair_pass(relay_b, publisher_b, ScanState(), subject_budget=4, now=T0)
        assert publisher_b.published == [], "B's reread under its own lock found the row completed"
        assert result_b_again.published == 0

    _run(scenario())

    assert parking.seqs_for("ref-owned") == [1], "exactly one delivery across both relays"
    assert _outbox(ledger_db, event_id)["published_at"] is not None


def test_the_second_relay_serves_an_independent_subject_while_the_first_holds_one(
    ledger_db: psycopg.Connection, relay_b: psycopg.Connection
) -> None:
    """One relay owning a subject does not stall the other: unrelated service continues."""
    _commit_coverage(ledger_db, "cov-held", count=1)
    _commit_referral(ledger_db, "ref-free", count=1)

    parking = ParkingPublisher()
    publisher_b = RecordingPublisher()

    async def scenario() -> None:
        worker_a = asyncio.create_task(relay_fair_pass(ledger_db, parking, ScanState(), subject_budget=4, now=T0))
        await parking.arrived.wait()  # A parked on `coverage/cov-held`, which sorts first

        result_b, _ = await relay_fair_pass(relay_b, publisher_b, ScanState(), subject_budget=4, now=T0)
        assert result_b.published == 1, "the independent subject was served while A held the other"
        assert result_b.deferred == 1, "A's subject was deferred, not waited on"

        parking.release.set()
        await worker_a

    _run(scenario())

    assert publisher_b.seqs_for("ref-free") == [1]
    assert publisher_b.seqs_for("cov-held") == [], "B never published the subject A owned"
    assert parking.seqs_for("cov-held") == [1]


def test_a_subject_taken_between_the_probe_and_the_publish_is_deferred_not_published(
    ledger_db: psycopg.Connection, relay_b: psycopg.Connection
) -> None:
    """The window the scan's probe opens: eligibility is decided for every selected subject up
    front, and the publish acquisition happens later — so a subject free at probe time can belong
    to another relay by the time this pass reaches it.

    Relay B probes both subjects while both are free, then parks publishing the first. Relay A
    takes the second meanwhile and parks holding it. When B resumes, its own acquisition must fail
    and the subject must be deferred: publishing on the strength of the stale probe would be a
    second, concurrent delivery of a row another relay owns.
    """
    _commit_coverage(ledger_db, "cov-first", count=1)
    [taken_id] = _commit_referral(ledger_db, "ref-taken", count=1)

    parking_b = ParkingPublisher()
    parking_a = ParkingPublisher()

    async def scenario() -> None:
        worker_b = asyncio.create_task(relay_fair_pass(relay_b, parking_b, ScanState(), subject_budget=4, now=T0))
        await parking_b.arrived.wait()  # B probed both subjects as free, and is publishing the first

        worker_a = asyncio.create_task(relay_fair_pass(ledger_db, parking_a, ScanState(), subject_budget=4, now=T0))
        await parking_a.arrived.wait()  # A now owns `referral/ref-taken` and is publishing it

        parking_b.release.set()
        result_b, _ = await worker_b
        assert result_b.published == 1, "B published only the subject it actually held"
        assert result_b.deferred == 1, "the subject A had taken cost B one selection, not a delivery"

        parking_a.release.set()
        await worker_a

    _run(scenario())

    assert parking_b.seqs_for("ref-taken") == [], "B did not publish on the strength of its stale probe"
    assert parking_a.seqs_for("ref-taken") == [1], "exactly one relay delivered the row"
    assert _outbox(ledger_db, taken_id)["attempts"] == 1, "one delivery, one attempt charged"


# --- 2. Ambiguous publishes ----------------------------------------------------------------------


def test_an_ambiguous_publish_redelivers_the_same_event_id_in_sequence_order(
    ledger_db: psycopg.Connection,
) -> None:
    """Spec: "Redelivery is deduplicable" and "Per-subject order holds across retries".

    The bus accepted `seq` 1 but the ack was lost, so the row was never marked. The next fair pass
    redelivers it with the same `event_id` ahead of the subject's later rows.
    """
    event_ids = _commit_referral(ledger_db, "ref-ambiguous", count=3)
    publisher = RecordingPublisher()

    _result, state = _run(relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=4, row_budget=1, now=T0))
    assert publisher.seqs_for("ref-ambiguous") == [1]
    # The ack was lost after the bus took the entry: the row goes back to pending, unchanged.
    ledger_db.execute("UPDATE ledger.outbox SET published_at = NULL WHERE event_id = %s", (event_ids[0],))

    _run(relay_fair_pass(ledger_db, publisher, state, subject_budget=4, row_budget=3, now=T0))

    assert publisher.seqs_for("ref-ambiguous") == [1, 1, 2, 3], "the redelivery leads, in sequence order"
    delivered = publisher.event_ids()
    assert delivered[0] == delivered[1] == str(event_ids[0]), "both deliveries carry one event id to dedupe on"


def test_a_worker_killed_mid_publish_redelivers_after_restart(
    ledger_db: psycopg.Connection, relay_b: psycopg.Connection
) -> None:
    """A worker dies between the bus accepting an entry and the outbox recording it.

    The replacement worker is a different connection with a fresh `ScanState` — the restart case
    where ephemeral scheduling state is gone and only durable outbox state carries over. The row is
    still pending, so it redelivers with the same `event_id`; nothing is lost and nothing skipped.
    """
    event_ids = _commit_referral(ledger_db, "ref-killed", count=2)
    parking = ParkingPublisher()
    after_restart = RecordingPublisher()

    async def scenario() -> None:
        worker = asyncio.create_task(relay_fair_pass(ledger_db, parking, ScanState(), subject_budget=4, now=T0))
        await parking.arrived.wait()  # the bus has `seq` 1; the outbox does not know yet
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    _run(scenario())

    assert parking.seqs_for("ref-killed") == [1]
    assert _outbox(ledger_db, event_ids[0])["published_at"] is None, "the dead worker marked nothing"

    # The restarted worker: new connection, scheduling state reset to the front of the ring.
    _run(relay_fair_pass(relay_b, after_restart, ScanState(), subject_budget=4, row_budget=2, now=T0))

    assert after_restart.seqs_for("ref-killed") == [1, 2], "pending work survived the restart, in order"
    assert after_restart.event_ids()[0] == str(event_ids[0]), "the redelivery is deduplicable on event id"
    assert all(_outbox(relay_b, event_id)["published_at"] is not None for event_id in event_ids)


# --- 3. Retry, dead-letter and manual redrive, under the fair pass -------------------------------


def _drive_until_dead_lettered(
    conn: psycopg.Connection, publisher: RecordingPublisher, *, subject_budget: int = 4
) -> ScanState:
    """Run `MAX_ATTEMPTS` fair passes, each one backoff window later than the last.

    Advancing `now` per pass is how a backoff window is crossed here: the relay's clock is an
    argument, so the retry schedule is exercised exactly and no test waits on one.
    """
    state = ScanState()
    for attempt in range(MAX_ATTEMPTS):
        _result, state = _run(
            relay_fair_pass(
                conn,
                publisher,
                state,
                subject_budget=subject_budget,
                row_budget=4,
                now=T0 + timedelta(minutes=attempt),
            )
        )
    return state


def test_five_failures_dead_letter_the_head_while_an_independent_subject_keeps_being_served(
    ledger_db: psycopg.Connection,
) -> None:
    """Spec: "Poison head retains existing retry policy" — unchanged by fair scheduling."""
    [poison_id] = _commit_referral(ledger_db, "ref-poison", count=1)
    _commit_coverage(ledger_db, "cov-healthy", count=2)
    publisher = RecordingPublisher(refuses=lambda event: event["subject_key"] == "ref-poison")
    assert dead_letter_depth(ledger_db) == 0

    _drive_until_dead_lettered(ledger_db, publisher)

    row = _outbox(ledger_db, poison_id)
    assert row["attempts"] == MAX_ATTEMPTS
    assert row["dead_lettered_at"] is not None
    assert row["next_attempt_at"] is None, "a dead-lettered row is not scheduled for another attempt"
    assert dead_letter_depth(ledger_db) >= 1, "the depth the monitor alarms on"
    assert publisher.seqs_for("cov-healthy") == [1, 2], "unrelated service continued throughout"


def test_only_manual_redrive_returns_a_dead_lettered_row_to_the_fair_pass(
    ledger_db: psycopg.Connection,
) -> None:
    """No amount of further scanning retries a dead-lettered row; the operator's redrive does."""
    [poison_id] = _commit_referral(ledger_db, "ref-redrive", count=1)
    failing = RecordingPublisher(refuses=lambda event: True)
    _drive_until_dead_lettered(ledger_db, failing)
    assert dead_letter_depth(ledger_db) == 1
    delivered_before = len(failing.published)

    healthy = RecordingPublisher()
    _run(relay_fair_pass(ledger_db, healthy, ScanState(), subject_budget=4, now=T0 + timedelta(hours=1)))
    assert healthy.published == [], "the relay never picks a dead-lettered row back up by itself"
    assert candidate_subjects(ledger_db) == [], "it has left the candidate set entirely"
    assert len(failing.published) == delivered_before

    assert redrive(ledger_db, poison_id) is True
    assert redrive(ledger_db, poison_id) is False, "a live row is not redrivable"

    _run(relay_fair_pass(ledger_db, healthy, ScanState(), subject_budget=4, now=T0 + timedelta(hours=2)))

    assert healthy.seqs_for("ref-redrive") == [1], "the redriven row is a possible late delivery"
    assert dead_letter_depth(ledger_db) == 0
    assert _outbox(ledger_db, poison_id)["attempts"] == 1, "redrive restored a full attempt budget"


def test_a_dead_lettered_head_stops_blocking_its_subjects_later_rows(
    ledger_db: psycopg.Connection,
) -> None:
    """The head's exhaustion frees the rest of its subject — the fair pass keeps that property."""
    event_ids = _commit_referral(ledger_db, "ref-blocked", count=3)
    publisher = RecordingPublisher(refuses=lambda event: event["seq"] == 1)

    _drive_until_dead_lettered(ledger_db, publisher)
    assert _outbox(ledger_db, event_ids[0])["dead_lettered_at"] is not None
    assert publisher.seqs_for("ref-blocked") == [], "nothing behind the head was published while it retried"

    _run(
        relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=4, row_budget=4, now=T0 + timedelta(hours=1))
    )

    assert publisher.seqs_for("ref-blocked") == [2, 3], "the freed rows follow, still in sequence order"


# --- 4. A backing-off head ------------------------------------------------------------------------


def test_a_backing_off_head_is_not_bypassed_and_does_not_monopolise_the_scan(
    ledger_db: psycopg.Connection, relay_b: psycopg.Connection
) -> None:
    """Spec: "Locked and backing-off heads do not monopolize scans".

    One subject is locked by a second, real relay connection; another's head is inside its retry
    window with due rows behind it; a third is plainly eligible. One scan cycle serves the third,
    publishes nothing for either unavailable subject, and in particular lets no later row of the
    backing-off subject overtake its head. When the window passes, the head goes first.
    """
    _commit_coverage(ledger_db, "cov-locked", count=1)
    backing_off = _commit_referral(ledger_db, "ref-backoff", count=3)
    _commit_referral(ledger_db, "ref-ready", count=1)
    ledger_db.execute(
        "UPDATE ledger.outbox SET attempts = 1, next_attempt_at = %s WHERE event_id = %s",
        (T0 + timedelta(minutes=5), backing_off[0]),
    )

    publisher = RecordingPublisher()
    parking = ParkingPublisher()

    async def scenario() -> None:
        holder = asyncio.create_task(relay_fair_pass(relay_b, parking, ScanState(), subject_budget=1, now=T0))
        await parking.arrived.wait()  # relay B parked holding `coverage/cov-locked`

        result, _state = await relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=3, now=T0)

        assert result.published == 1, "the one eligible subject was served in the same cycle"
        assert result.deferred == 2, "the locked and the backing-off subject each cost one selection"
        parking.release.set()
        await holder

    _run(scenario())

    assert publisher.seqs_for("ref-ready") == [1]
    assert publisher.seqs_for("ref-backoff") == [], "no later row bypassed the backing-off head"
    assert publisher.seqs_for("cov-locked") == [], "the locked subject stayed the other relay's work"

    # Past the window: the head publishes first, then what was queued behind it.
    _run(
        relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=3, row_budget=3, now=T0 + timedelta(hours=1))
    )

    assert publisher.seqs_for("ref-backoff") == [1, 2, 3]


def test_a_row_inside_its_retry_window_is_not_overtaken_within_a_pass(
    ledger_db: psycopg.Connection,
) -> None:
    """The subject is eligible — its *head* is due — but a later row of it is still backing off.

    The scan cannot catch this one: eligibility is decided on the head alone, so the guarantee
    rests entirely on publication stopping at the first row inside its window. `seq` 3 must not
    overtake a waiting `seq` 2, and both follow once the window has passed.
    """
    event_ids = _commit_referral(ledger_db, "ref-midbackoff", count=3)
    ledger_db.execute(
        "UPDATE ledger.outbox SET attempts = 1, next_attempt_at = %s WHERE event_id = %s",
        (T0 + timedelta(minutes=5), event_ids[1]),
    )
    publisher = RecordingPublisher()

    result, _state = _run(relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=3, row_budget=3, now=T0))

    assert publisher.seqs_for("ref-midbackoff") == [1], "publication stopped at the waiting row"
    assert result.deferred == 2, "the waiting row and the one behind it are both deferred"

    _run(
        relay_fair_pass(ledger_db, publisher, ScanState(), subject_budget=3, row_budget=3, now=T0 + timedelta(hours=1))
    )

    assert publisher.seqs_for("ref-midbackoff") == [1, 2, 3]


# --- 5. Restart between passes --------------------------------------------------------------------


def test_restart_with_reset_scan_state_preserves_durable_delivery_state(
    ledger_db: psycopg.Connection, relay_b: psycopg.Connection
) -> None:
    """Spec: "Restart preserves pending work".

    A worker advances its scan and publishes durably; the replacement starts from a fresh
    `ScanState` on another connection. Completed rows are not pending again, pending rows are still
    available, and the new scan still completes a cycle over the remaining finite set within its
    `ceil(N / B)` bound.
    """
    subjects = [f"ref-{index:02d}" for index in range(5)]
    for key in subjects:
        _commit_referral(ledger_db, key, count=1)
    budget = 2
    before = RecordingPublisher()

    state = ScanState()
    for _ in range(2):
        _result, state = _run(relay_fair_pass(ledger_db, before, state, subject_budget=budget, now=T0))
    published_before = {event["subject_key"] for event in before.published}
    assert published_before, "the pre-restart worker made durable progress"

    # Restart: ephemeral scan position discarded, durable outbox state is all that carries over.
    remaining = candidate_subjects(relay_b)
    assert {key for _type, key in remaining} == set(subjects) - published_before, "completed rows are not pending"

    after = RecordingPublisher()
    restarted = ScanState()
    for _ in range(math.ceil(len(remaining) / budget)):
        _result, restarted = _run(relay_fair_pass(relay_b, after, restarted, subject_budget=budget, now=T0))

    assert {event["subject_key"] for event in after.published} == set(subjects) - published_before
    assert candidate_subjects(relay_b) == [], "the restarted scan completed its cycle within the bound"
    delivered = before.event_ids() + after.event_ids()
    assert len(delivered) == len(set(delivered)) == len(subjects), "each row delivered exactly once across restart"


# --- 6. Continuous hot-subject traffic ------------------------------------------------------------


def test_continuous_hot_subject_traffic_does_not_starve_a_cold_subject(
    ledger_db: psycopg.Connection,
) -> None:
    """Spec: "Skewed backlog cannot starve an independent subject", with the backlog replenished.

    `coverage/cov-hot` sorts ahead of `referral/ref-cold` and takes two new events before every
    pass, so its backlog never empties — the condition under which the old `LIMIT` query would have
    read nothing but the hot subject forever. The scan's cursor still reaches the cold subject
    within `ceil(N / B)` passes, and the hot subject keeps draining meanwhile.
    """
    _commit_coverage(ledger_db, "cov-hot", count=2)
    _commit_referral(ledger_db, "ref-cold", count=1)
    publisher = RecordingPublisher()
    n, budget = 2, 1

    state = ScanState()
    for index in range(math.ceil(n / budget)):
        _commit_coverage(ledger_db, "cov-hot", count=2, start=2 + index * 2)  # traffic arriving between passes
        _result, state = _run(relay_fair_pass(ledger_db, publisher, state, subject_budget=budget, row_budget=2, now=T0))

    assert publisher.seqs_for("ref-cold") == [1], "the cold subject was served within the scan-cycle bound"
    assert publisher.seqs_for("cov-hot") == [1, 2], "the hot subject kept being served, bounded per pass"
    assert ("coverage", "cov-hot") in candidate_subjects(ledger_db), "its newer arrivals wait for its next turn"
