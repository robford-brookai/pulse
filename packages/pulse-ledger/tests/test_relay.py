"""The outbox relay — task 4.4's three test obligations, against a real Postgres.

1. **Order across retry**: a subject's events 1..3 with 2 failing transiently reach the bus 1, 2, 3.
2. **Poison row dead-letters and relay continues**: five failures move a row to the DLQ, the depth
   the monitor reads goes to 1, and other subjects keep flowing throughout.
3. **No publish without commit**: a rolled-back command leaves no outbox row, so the relay has
   nothing to publish.

Plus the surrounding promises: at-least-once redelivery carries the same `event_id`, the lag gauge
the p99 < 30 s SLO is stated over, backoff is durable across passes, two relays do not both take
one subject, and redrive is the operator's action.

The publisher is a fake satisfying `relay.Publisher`. That is the point of the protocol: ordering
and dead-lettering are decisions this module makes, and asserting them needs a bus that fails on
command, not AWS.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_ledger import relay as relay_module
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.relay import (
    MAX_ATTEMPTS,
    PendingRow,
    RelayPass,
    dead_letter_depth,
    outbox_lag_seconds,
    pending_rows,
    redrive,
    relay_once,
)

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

#: Legal forward paths for the two subject types these tests drive, so a three-event history is a
#: real one rather than a sequence the catalog would reject.
REFERRAL_STATES = ("received", "resolved", "screened")


class BusRefused(RuntimeError):
    """What the fake bus raises, standing in for whatever a real transport failure looks like."""

    def __init__(self, reason: str = "bus refused the entry") -> None:
        super().__init__(reason)


@dataclass
class FakePublisher:
    """A bus that records what it accepted and refuses whatever `fail_seqs` names.

    `fail_seqs` is keyed by the envelope's `seq`, which is what makes "event 2 fails transiently"
    expressible: clear the entry and the next attempt succeeds.
    """

    fail_seqs: set[int] = field(default_factory=set)
    fail_subjects: set[str] = field(default_factory=set)
    published: list[dict[str, Any]] = field(default_factory=list)
    keys: list[str | None] = field(default_factory=list)

    async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
        if event["seq"] in self.fail_seqs or event["subject_key"] in self.fail_subjects:
            raise BusRefused
        self.published.append(event)
        self.keys.append(key)

    def seqs_for(self, subject_key: str) -> list[int]:
        return [event["seq"] for event in self.published if event["subject_key"] == subject_key]


def _declare(subject_key: str, to_state: str, effective_at: datetime) -> Declaration:
    return Declaration(
        subject_type="referral",
        subject_key=subject_key,
        event_type=f"referral.{to_state}",
        to_state=to_state,
        effective_at=effective_at,
        actor_type="system",
        actor_id="relay-tests",
        producer="pulse-ledger-tests",
        payload={"note": "synthetic"},
    )


def _commit_history(conn: psycopg.Connection, subject_key: str, count: int = 3) -> list[uuid.UUID]:
    """Commit `count` legal forward events for one subject and return their ids in order."""
    ids = []
    for index in range(count):
        result = commit_declaration(conn, _declare(subject_key, REFERRAL_STATES[index], T0 + timedelta(hours=index)))
        ids.append(result.event_id)
    return ids


def _run(coro: Any) -> RelayPass:
    """Drive one relay pass. The relay is async because the shared publisher is."""
    return asyncio.run(coro)  # type: ignore[no-any-return]


def _outbox(conn: psycopg.Connection, event_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT attempts, published_at, dead_lettered_at, next_attempt_at, last_error"
        " FROM ledger.outbox WHERE event_id = %s",
        (event_id,),
    ).fetchone()
    assert row is not None
    names = ("attempts", "published_at", "dead_lettered_at", "next_attempt_at", "last_error")
    return dict(zip(names, row, strict=True))


# --- 1. No publish without commit -------------------------------------------------------------


def test_a_rolled_back_command_leaves_nothing_for_the_relay(ledger_db: psycopg.Connection) -> None:
    """The outbox row is written inside the command's transaction, so a rollback takes it too."""
    with pytest.raises(BusRefused, match="injected"), ledger_db.transaction():
        commit_declaration(ledger_db, _declare("ref-rollback", "received", T0))
        # The command failed after the commit and before the caller was answered — the whole
        # transaction, outbox row included, goes away.
        raise BusRefused("injected")

    assert pending_rows(ledger_db) == []
    publisher = FakePublisher()
    result = _run(relay_once(ledger_db, publisher))
    assert publisher.published == []
    assert result == RelayPass()


def test_the_relay_publishes_only_what_the_outbox_holds(ledger_db: psycopg.Connection) -> None:
    """An event with no outbox row is not published — the outbox is the only source of truth."""
    event_ids = _commit_history(ledger_db, "ref-only-outbox", count=2)
    ledger_db.execute("DELETE FROM ledger.outbox WHERE event_id = %s", (event_ids[1],))

    publisher = FakePublisher()
    _run(relay_once(ledger_db, publisher))

    assert [event["event_id"] for event in publisher.published] == [str(event_ids[0])]


# --- 2. Per-subject order across retry ---------------------------------------------------------


def test_per_subject_order_holds_across_a_transient_failure(ledger_db: psycopg.Connection) -> None:
    """Events 1..3 with 2 failing transiently reach the bus in sequence order 1, 2, 3."""
    _commit_history(ledger_db, "ref-order", count=3)
    publisher = FakePublisher(fail_seqs={2})

    first = _run(relay_once(ledger_db, publisher))
    assert publisher.seqs_for("ref-order") == [1], "seq 3 must not overtake a failing seq 2"
    assert first.published == 1
    assert first.retried == 1
    assert first.deferred == 1

    publisher.fail_seqs.clear()
    # Past the backoff window the failure scheduled.
    _run(relay_once(ledger_db, publisher, now=datetime.now(tz=timezone.utc) + timedelta(minutes=5)))

    assert publisher.seqs_for("ref-order") == [1, 2, 3]


def test_a_backoff_window_defers_the_whole_subject(ledger_db: psycopg.Connection) -> None:
    """A retry inside its backoff window publishes nothing for that subject, not just the head."""
    _commit_history(ledger_db, "ref-backoff", count=3)
    publisher = FakePublisher(fail_seqs={1})
    _run(relay_once(ledger_db, publisher))
    assert publisher.published == []

    publisher.fail_seqs.clear()
    result = _run(relay_once(ledger_db, publisher))

    assert publisher.published == [], "the row is still backing off; nothing behind it may pass"
    assert result.deferred == 3
    assert _outbox(ledger_db, pending_rows(ledger_db)[0].event_id)["attempts"] == 1


def test_a_failing_subject_does_not_stall_the_others(ledger_db: psycopg.Connection) -> None:
    """Head-of-line blocking is per subject; cross-subject order is neither promised nor enforced."""
    _commit_history(ledger_db, "ref-stuck", count=2)
    _commit_history(ledger_db, "ref-healthy", count=2)
    publisher = FakePublisher(fail_subjects={"ref-stuck"})

    _run(relay_once(ledger_db, publisher))

    assert publisher.seqs_for("ref-stuck") == []
    assert publisher.seqs_for("ref-healthy") == [1, 2]


def test_the_publisher_is_keyed_by_subject(ledger_db: psycopg.Connection) -> None:
    """The grouping key is the subject — the grain the ordering promise is made on."""
    _commit_history(ledger_db, "ref-keyed", count=1)
    publisher = FakePublisher()
    _run(relay_once(ledger_db, publisher))
    assert publisher.keys == ["referral/ref-keyed"]


# --- At-least-once ------------------------------------------------------------------------------


def test_redelivery_carries_the_same_event_id(ledger_db: psycopg.Connection) -> None:
    """An ambiguous publish redelivers rather than disappears, and a consumer can dedupe it."""
    [event_id] = _commit_history(ledger_db, "ref-redeliver", count=1)
    publisher = FakePublisher()

    _run(relay_once(ledger_db, publisher))
    # The bus accepted the entry but the ack was lost, so the row was never marked.
    ledger_db.execute("UPDATE ledger.outbox SET published_at = NULL WHERE event_id = %s", (event_id,))
    _run(relay_once(ledger_db, publisher))

    assert [event["event_id"] for event in publisher.published] == [str(event_id), str(event_id)]


def test_a_published_row_is_not_published_again(ledger_db: psycopg.Connection) -> None:
    """The ordinary case: marking is what keeps at-least-once from being every-pass."""
    _commit_history(ledger_db, "ref-once", count=2)
    publisher = FakePublisher()
    _run(relay_once(ledger_db, publisher))
    _run(relay_once(ledger_db, publisher))
    assert len(publisher.published) == 2


# --- 3. Poison row dead-letters, relay continues -----------------------------------------------


def test_five_failures_dead_letter_the_row_and_alarm_the_monitor(ledger_db: psycopg.Connection) -> None:
    """The fifth failure marks the row, the DLQ depth the monitor alarms on becomes 1."""
    [event_id] = _commit_history(ledger_db, "ref-poison", count=1)
    publisher = FakePublisher(fail_subjects={"ref-poison"})
    assert dead_letter_depth(ledger_db) == 0

    for attempt in range(MAX_ATTEMPTS):
        # Each pass runs past the previous failure's backoff window.
        _run(relay_once(ledger_db, publisher, now=datetime.now(tz=timezone.utc) + timedelta(hours=attempt)))

    row = _outbox(ledger_db, event_id)
    assert row["attempts"] == MAX_ATTEMPTS
    assert row["dead_lettered_at"] is not None
    assert row["next_attempt_at"] is None, "a dead-lettered row has no next attempt"
    assert "bus refused the entry" in row["last_error"]
    assert dead_letter_depth(ledger_db) == 1
    assert publisher.published == []


def test_a_dead_lettered_row_leaves_the_relay_alone(ledger_db: psycopg.Connection) -> None:
    """Relay of other subjects continues, and the poison row is not rescanned every pass."""
    _commit_history(ledger_db, "ref-dead", count=1)
    publisher = FakePublisher(fail_subjects={"ref-dead"})
    for attempt in range(MAX_ATTEMPTS):
        _run(relay_once(ledger_db, publisher, now=datetime.now(tz=timezone.utc) + timedelta(hours=attempt)))
    assert dead_letter_depth(ledger_db) == 1

    _commit_history(ledger_db, "ref-after", count=2)
    result = _run(relay_once(ledger_db, publisher))

    assert publisher.seqs_for("ref-after") == [1, 2]
    assert [row.subject_key for row in pending_rows(ledger_db)] == []
    assert result.dead_lettered == 0, "the poison row is out of the claim path, not re-charged"


def test_the_dlq_reason_is_the_transports_and_carries_no_envelope(ledger_db: psycopg.Connection) -> None:
    """`last_error` is for triage. The envelope — payload and evidence with it — never enters it."""
    [event_id] = _commit_history(ledger_db, "ref-reason", count=1)
    publisher = FakePublisher(fail_subjects={"ref-reason"})
    for attempt in range(MAX_ATTEMPTS):
        _run(relay_once(ledger_db, publisher, now=datetime.now(tz=timezone.utc) + timedelta(hours=attempt)))

    last_error = _outbox(ledger_db, event_id)["last_error"]
    assert last_error == "BusRefused: bus refused the entry"
    assert "synthetic" not in last_error, "the payload has no business in an error column"


def test_a_very_long_failure_reason_is_truncated(ledger_db: psycopg.Connection) -> None:
    """A transport error can be a whole response body; the column is triage, not archival."""

    class Verbose:
        async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
            raise BusRefused("x" * 5000)

    [event_id] = _commit_history(ledger_db, "ref-verbose", count=1)
    _run(relay_once(ledger_db, Verbose()))
    assert len(_outbox(ledger_db, event_id)["last_error"]) == relay_module._MAX_ERROR_CHARS


def test_redrive_is_the_operators_action(ledger_db: psycopg.Connection) -> None:
    """Nothing automatic returns a dead-lettered row; clearing the marker restores a full budget."""
    [event_id] = _commit_history(ledger_db, "ref-redrive", count=1)
    publisher = FakePublisher(fail_subjects={"ref-redrive"})
    for attempt in range(MAX_ATTEMPTS):
        _run(relay_once(ledger_db, publisher, now=datetime.now(tz=timezone.utc) + timedelta(hours=attempt)))

    assert redrive(ledger_db, event_id) is True
    assert redrive(ledger_db, event_id) is False, "a live row is not redrivable"
    assert _outbox(ledger_db, event_id)["attempts"] == 0
    assert dead_letter_depth(ledger_db) == 0

    publisher.fail_subjects.clear()
    _run(relay_once(ledger_db, publisher))
    assert publisher.seqs_for("ref-redrive") == [1]


# --- Lag and envelope ---------------------------------------------------------------------------


def test_lag_is_the_age_of_the_oldest_waiting_row(ledger_db: psycopg.Connection) -> None:
    """The gauge the p99 < 30 s outbox-to-backbone SLO is stated over."""
    assert outbox_lag_seconds(ledger_db) is None

    _commit_history(ledger_db, "ref-lag", count=1)
    created_at = pending_rows(ledger_db)[0].created_at
    assert outbox_lag_seconds(ledger_db, now=created_at + timedelta(seconds=42)) == pytest.approx(42.0)

    result = _run(relay_once(ledger_db, FakePublisher()))
    assert outbox_lag_seconds(ledger_db) is None
    assert result.max_lag_seconds is not None and result.max_lag_seconds >= 0


def test_a_dead_lettered_row_does_not_peg_the_lag_gauge(ledger_db: psycopg.Connection) -> None:
    """It is an alarm of its own; leaving it in the gauge would mask every real lag reading."""
    _commit_history(ledger_db, "ref-lag-dead", count=1)
    publisher = FakePublisher(fail_subjects={"ref-lag-dead"})
    for attempt in range(MAX_ATTEMPTS):
        _run(relay_once(ledger_db, publisher, now=datetime.now(tz=timezone.utc) + timedelta(hours=attempt)))

    assert dead_letter_depth(ledger_db) == 1
    assert outbox_lag_seconds(ledger_db) is None


def test_the_envelope_carries_what_a_consumer_needs(ledger_db: psycopg.Connection) -> None:
    """Identity for dedupe, the subject and `seq` for the ordering guard, the fact itself."""
    [event_id] = _commit_history(ledger_db, "ref-envelope", count=1)
    publisher = FakePublisher()
    _run(relay_once(ledger_db, publisher))

    envelope = publisher.published[0]
    assert envelope["event_id"] == str(event_id)
    assert envelope["event_type"] == "referral.received"
    assert (envelope["subject_type"], envelope["subject_key"], envelope["seq"]) == ("referral", "ref-envelope", 1)
    # `effective_at` is canonical and `occurred_at` is its alias, the same pairing the write path
    # accepts — so a consumer written against either name reads one fact, not two.
    assert envelope["occurred_at"] == envelope["effective_at"]
    assert envelope["actor"] == {"type": "system", "id": "relay-tests", "authority": None}
    assert envelope["payload"]["note"] == "synthetic"
    assert envelope["schema_version"] == 1
    assert envelope["reverses_event_id"] is None


# --- Concurrency ---------------------------------------------------------------------------------


def test_a_subject_held_by_another_relay_is_left_alone(ledger_db: psycopg.Connection, pg_database: dict) -> None:
    """Two relays never publish one subject's rows at once — that is how order survives them."""
    _commit_history(ledger_db, "ref-locked", count=2)
    key = "referral\x1fref-locked"
    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as other:
        held = other.execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (relay_module._RELAY_LOCK_NAMESPACE, key)
        ).fetchone()
        assert held is not None and held[0] is True

        publisher = FakePublisher()
        result = _run(relay_once(ledger_db, publisher))

    assert publisher.published == []
    assert result.deferred == 2


def test_the_relay_lock_does_not_block_a_writer(ledger_db: psycopg.Connection, pg_database: dict) -> None:
    """The relay's namespace is not the commit path's, so relaying never stalls a commit."""
    _commit_history(ledger_db, "ref-writer", count=1)

    class Slow:
        async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
            # A second writer commits for the same subject while the relay holds its lock.
            with psycopg.connect(
                host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
            ) as writer:
                writer.execute("SET lock_timeout = '3s'")
                commit_declaration(writer, _declare("ref-writer", "resolved", T0 + timedelta(hours=1)))

    _run(relay_once(ledger_db, Slow()))
    assert len(pending_rows(ledger_db)) == 1, "the writer's own commit landed, unblocked"


# --- Batching -------------------------------------------------------------------------------------


def test_a_batch_bounds_the_pass_without_reordering(ledger_db: psycopg.Connection) -> None:
    """The remainder is the next pass's work; a truncated subject still goes in `seq` order."""
    _commit_history(ledger_db, "ref-batch", count=3)
    publisher = FakePublisher()

    _run(relay_once(ledger_db, publisher, batch_size=2))
    assert publisher.seqs_for("ref-batch") == [1, 2]
    _run(relay_once(ledger_db, publisher, batch_size=2))
    assert publisher.seqs_for("ref-batch") == [1, 2, 3]


def test_pending_rows_expose_the_subject_and_routing_key(ledger_db: psycopg.Connection) -> None:
    _commit_history(ledger_db, "ref-shape", count=1)
    [row] = pending_rows(ledger_db)
    assert isinstance(row, PendingRow)
    assert row.subject == ("referral", "ref-shape")
    assert row.routing_key == "referral/ref-shape"


# --- Wiring ---------------------------------------------------------------------------------------


def test_the_default_publisher_owns_no_second_queue() -> None:
    """D7's wiring: the shared publisher, in raise mode, because the outbox is already the queue.

    `ocean-broker` needs Python 3.13 and boto3 while this package supports 3.10 — the skip is the
    same reason `default_publisher` imports lazily rather than at module scope.
    """
    pytest.importorskip("ocean_broker")
    from unittest.mock import patch

    with patch("ocean_broker.publisher.boto3"):
        publisher = relay_module.default_publisher()

    assert publisher._on_failure == "raise"  # type: ignore[attr-defined]
    assert publisher._db_session_maker is None  # type: ignore[attr-defined]
