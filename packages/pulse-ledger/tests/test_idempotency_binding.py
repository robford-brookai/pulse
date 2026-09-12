"""Binding-checked replay in the commit path — task 2.1, against a real Postgres.

The scenarios this covers are `command-api`'s "Mismatched key reuse is rejected", "Canonical exact
retry remains compatible", "Concurrent binding claim is atomic" and "Original result survives later
corrections". Everything here runs `commit_idempotent` with a `Writer`, which is what turns the
binding on: the unbound calls in `test_idempotent_commit.py` are the same path before enforcement,
and both postures are tested rather than one being assumed.

Three properties get most of the weight:

- **Both halves, or conflict.** A replay requires the same authenticated writer *and* the same
  canonical fingerprint. Every other combination raises `IdempotencyConflictError`, which carries
  the same reason whichever half mismatched — a caller must not be able to probe what a key already
  holds — and no original event id, result or fingerprint travels with it.
- **A conflict writes nothing.** Not an event, not a key, not an outbox row, not a binding. Asserted
  by row counts after each rejection, including on the race-loser path where the attempt did write
  its rows before the conflict was detected.
- **The replayed result is the original's, by sequence rather than by clock.** Later history is
  excluded on the outbox `seq` the original commit was assigned, so a same-`recorded_at` event and a
  transaction that started before the original but committed after it are both outside the answer.

The races run on two real connections. Where a race would otherwise be timing-dependent, the same
mechanism is also driven deterministically by blinding the pre-check, so the loser's recovery path
is exercised on every run and not only when the two threads happen to overlap.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_core.idempotency import derive_idempotency_key
from pulse_ledger import idempotency as idempotency_module
from pulse_ledger.auth import Writer
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration, commit_reversal
from pulse_ledger.idempotency import (
    IDEMPOTENCY_CONFLICT,
    IDEMPOTENCY_LEGACY_UNVERIFIABLE,
    IdempotencyConflictError,
    commit_idempotent,
)
from pulse_ledger.request_fingerprint import FINGERPRINT_VERSION, request_fingerprint
from pulse_ledger.validation import IllegalTransitionError

SERVICE_ROLE = "pulse_ledger_service"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

RELAY = Writer(writer_id="verdict-relay")
RECONCILIATION = Writer(writer_id="reconciliation")


def _declare(
    subject_type: str = "referral",
    subject_key: str = "ref-1",
    to_state: str = "received",
    effective_at: datetime | None = None,
    writer: Writer = RELAY,
    **overrides: Any,
) -> Declaration:
    """One declaration attributed the way the boundary attributes it — from the credential."""
    fields: dict[str, Any] = {
        "subject_type": subject_type,
        "subject_key": subject_key,
        "event_type": f"{subject_type}.{to_state}",
        "to_state": to_state,
        "effective_at": effective_at or T0,
        "actor_type": writer.actor_type,
        "actor_id": writer.actor_id,
        "actor_authority": writer.actor_authority,
        "producer": writer.writer_id,
    }
    fields.update(overrides)
    return Declaration(**fields)


def _key_for(declaration: Declaration, *, writer_id: str = "verdict-relay") -> str:
    return derive_idempotency_key(
        writer_id=writer_id,
        subject_type=declaration.subject_type,
        subject_key=declaration.subject_key,
        command_type="declare_transition",
        payload=dict(declaration.event_payload()),
        logical_time=declaration.effective_at,
    )


def _rows(conn: psycopg.Connection, table: str) -> list[tuple[Any, ...]]:
    return conn.execute(f"SELECT * FROM ledger.{table}").fetchall()  # noqa: S608


def _bindings(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT key, writer_id, fingerprint_version, fingerprint, event_id"
        " FROM ledger.idempotency_bindings ORDER BY key"
    ).fetchall()


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    """The four row counts a conflict must leave untouched."""
    return {
        table: len(_rows(conn, table)) for table in ("events", "idempotency_keys", "outbox", "idempotency_bindings")
    }


# --- the binding is written with the commit ----------------------------------------------------


def test_a_bound_commit_records_the_writer_and_the_canonical_fingerprint(ledger_db: psycopg.Connection) -> None:
    declaration = _declare()
    key = _key_for(declaration)

    result = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert result.replayed is False
    assert _bindings(ledger_db) == [
        (key, RELAY.writer_id, FINGERPRINT_VERSION, request_fingerprint(declaration), result.event_id)
    ]


def test_the_binding_names_the_event_its_own_key_claimed(ledger_db: psycopg.Connection) -> None:
    """The composite foreign key makes "the binding's event" and "the key's event" one fact."""
    declaration = _declare()
    key = _key_for(declaration)
    result = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert ledger_db.execute(
        "SELECT b.event_id = k.event_id FROM ledger.idempotency_bindings b"
        " JOIN ledger.idempotency_keys k ON k.key = b.key WHERE b.key = %s",
        (key,),
    ).fetchone() == (True,)
    assert ledger_db.execute("SELECT event_id FROM ledger.idempotency_keys").fetchone() == (result.event_id,)


@pytest.mark.critical
def test_an_exact_retry_by_the_bound_writer_replays_and_writes_nothing(ledger_db: psycopg.Connection) -> None:
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    before = _counts(ledger_db)

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert replay.replayed is True
    assert replay.event_id == first.event_id
    assert replay.recorded_at == first.recorded_at
    assert replay.outbox_seq == first.outbox_seq
    assert replay.state == first.state
    assert _counts(ledger_db) == before


def test_an_equivalent_spelling_of_the_same_request_still_replays(ledger_db: psycopg.Connection) -> None:
    """Compatibility is the acceptance criterion: a retry may spell UTC and object keys differently.

    Same instant in another offset, same evidence members in another order. The fingerprint
    normalises both, so the writer gets the original result rather than a conflict.
    """
    original = _declare(evidence={"rule_id": "r-1", "matched_fields": ["mrn", "dob"]})
    key = _key_for(original)
    first = commit_idempotent(ledger_db, original, idempotency_key=key, writer=RELAY)

    retry = _declare(
        effective_at=T0.astimezone(timezone(timedelta(hours=2))),
        evidence={"matched_fields": ["mrn", "dob"], "rule_id": "r-1"},
    )
    replay = commit_idempotent(ledger_db, retry, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, first.event_id)
    assert len(_rows(ledger_db, "events")) == 1


def test_a_semantically_different_value_under_the_same_key_is_not_an_equivalent_spelling(
    ledger_db: psycopg.Connection,
) -> None:
    """The other side of the same rule: list order is meaning, so reordering it is a new request."""
    original = _declare(evidence={"matched_fields": ["mrn", "dob"]})
    key = _key_for(original)
    commit_idempotent(ledger_db, original, idempotency_key=key, writer=RELAY)
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError):
        commit_idempotent(
            ledger_db, _declare(evidence={"matched_fields": ["dob", "mrn"]}), idempotency_key=key, writer=RELAY
        )

    assert _counts(ledger_db) == before


# --- mismatched reuse is rejected, and rejection writes nothing ---------------------------------


@pytest.mark.critical
def test_the_bound_writer_changing_the_request_conflicts_and_writes_nothing(ledger_db: psycopg.Connection) -> None:
    declaration = _declare()
    key = _key_for(declaration)
    commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    before = _counts(ledger_db)

    # Legal on its own merits — only the binding can stop it.
    changed = _declare(to_state="resolved", effective_at=T0 + timedelta(days=1))
    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, changed, idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_CONFLICT
    assert raised.value.idempotency_key == key
    assert _counts(ledger_db) == before


@pytest.mark.critical
def test_another_authenticated_writer_reusing_the_key_conflicts_and_writes_nothing(
    ledger_db: psycopg.Connection,
) -> None:
    """The same request text under a second credential is a collision, not a replay (D15)."""
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, _declare(writer=RECONCILIATION), idempotency_key=key, writer=RECONCILIATION)

    assert raised.value.reason == IDEMPOTENCY_CONFLICT
    assert _counts(ledger_db) == before
    assert _bindings(ledger_db)[0][1] == RELAY.writer_id
    assert [row[0] for row in _rows(ledger_db, "events")] == [first.event_id]


def test_a_conflict_discloses_neither_the_original_result_nor_the_fingerprint(
    ledger_db: psycopg.Connection,
) -> None:
    """A generic conflict, so a caller cannot probe a key for what it holds (design decision 3).

    Both halves mismatching and one half mismatching produce the same reason and the same message,
    and neither carries the original event id, the writer of record, or either fingerprint — which
    is derived from payload and evidence and is therefore not safe to hand back.
    """
    declaration = _declare(evidence={"rule_id": "r-1"})
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    other = _declare(writer=RECONCILIATION, evidence={"rule_id": "r-2"})

    with pytest.raises(IdempotencyConflictError) as same_writer:
        commit_idempotent(ledger_db, _declare(evidence={"rule_id": "r-2"}), idempotency_key=key, writer=RELAY)
    with pytest.raises(IdempotencyConflictError) as other_writer:
        commit_idempotent(ledger_db, other, idempotency_key=key, writer=RECONCILIATION)

    assert str(same_writer.value) == str(other_writer.value)
    assert same_writer.value.reason == other_writer.value.reason
    for raised in (same_writer, other_writer):
        message = str(raised.value)
        assert str(first.event_id) not in message
        assert RELAY.writer_id not in message
        assert request_fingerprint(declaration) not in message
        assert request_fingerprint(other) not in message
        assert raised.value.__dict__.keys() <= {"idempotency_key", "reason"}


def test_a_rejected_bound_command_claims_neither_key_nor_binding(ledger_db: psycopg.Connection) -> None:
    """A rejection must not burn the key — the writer's corrected retry has to be able to commit."""
    illegal = _declare(to_state="outreach")
    key = _key_for(illegal)

    with pytest.raises(IllegalTransitionError):
        commit_idempotent(ledger_db, illegal, idempotency_key=key, writer=RELAY)

    assert _counts(ledger_db) == {"events": 0, "idempotency_keys": 0, "outbox": 0, "idempotency_bindings": 0}


def test_a_failure_after_the_binding_insert_leaves_no_event_key_or_binding(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Event, key and binding are claimed atomically: a failure takes all three (design decision 3)."""
    injected = RuntimeError("connection dropped before commit")
    real_bind = idempotency_module._bind

    def _bind_then_fail(conn: psycopg.Connection, binding: object, event_id: uuid.UUID) -> None:
        real_bind(conn, binding, event_id)  # type: ignore[arg-type]
        raise injected

    monkeypatch.setattr(idempotency_module, "_bind", _bind_then_fail)
    declaration = _declare()
    key = _key_for(declaration)
    with pytest.raises(RuntimeError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    assert raised.value is injected

    assert _counts(ledger_db) == {"events": 0, "idempotency_keys": 0, "outbox": 0, "idempotency_bindings": 0}

    # And the key is free, so the writer's retry commits rather than conflicting with a phantom.
    monkeypatch.undo()
    assert commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY).replayed is False


# --- keys without a binding, in both directions -------------------------------------------------


def test_a_legacy_key_whose_event_proves_no_writer_is_refused_with_its_own_reason(
    ledger_db: psycopg.Connection,
) -> None:
    """A key claimed before this change is replayed only from what its original event proves.

    Here it proves nothing: `producer` disagrees with `actor_id`, so no resolved credential stamped
    the event and no writer is established (D15). The answer is the distinct legacy reason and no
    binding is written — never a guess. The provable direction, where the rebuild succeeds and the
    key binds on first retry, is `test_legacy_idempotency_binding.py` (task 2.2).
    """
    declaration = _declare(producer="migration-loader")
    key = _key_for(declaration)
    commit_idempotent(ledger_db, declaration, idempotency_key=key)  # unbound: the pre-change path
    assert _bindings(ledger_db) == []
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE
    assert _counts(ledger_db) == before


def test_an_unbound_caller_is_never_answered_with_a_bound_writers_result(ledger_db: psycopg.Connection) -> None:
    """The reverse direction: a caller presenting no credential cannot collect a bound key's event."""
    declaration = _declare()
    key = _key_for(declaration)
    commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key)

    assert raised.value.reason == IDEMPOTENCY_CONFLICT
    assert _counts(ledger_db) == before


# --- the original result is the original's, by sequence rather than by clock --------------------


def test_a_replay_after_a_reversal_returns_the_original_event_and_the_original_state(
    ledger_db: psycopg.Connection,
) -> None:
    """A reversal corrects state; it does not free the key or change the answer already given."""
    commit_declaration(ledger_db, _declare())
    mistake = _declare(to_state="closed", effective_at=T0 + timedelta(days=1))
    key = _key_for(mistake)
    committed = commit_idempotent(ledger_db, mistake, idempotency_key=key, writer=RELAY)
    commit_reversal(
        ledger_db,
        reverses_event_id=committed.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-tests",
        reason="closed_in_error",
    )

    replay = commit_idempotent(ledger_db, mistake, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, committed.event_id)
    assert replay.state == committed.state
    assert len(_rows(ledger_db, "events")) == 3


def test_an_event_recorded_at_the_same_instant_is_not_part_of_the_original_answer(
    ledger_db: psycopg.Connection,
) -> None:
    """The snapshot boundary is the original commit's outbox `seq`, not its `recorded_at`.

    `recorded_at` is `clock_timestamp()` and distinct in practice, but nothing in the schema makes
    it unique — a coarse clock, a restore, or a corrected row can tie two events. A tie must not
    pull a later event into an earlier commit's replayed state, so the tie is forced here and the
    replay is required to ignore it.
    """
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    later = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=1)))
    ledger_db.execute(
        "UPDATE ledger.events SET recorded_at = %s WHERE event_id = %s", (first.recorded_at, later.event_id)
    )

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert replay.state is not None
    assert replay.state.state == "received"
    assert replay.state.event_id == first.event_id
    assert replay.outbox_seq == first.outbox_seq


def test_a_transaction_that_started_first_but_committed_later_is_outside_the_answer(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """Transaction start order is not commit order, and the replay follows commit order.

    A second connection opens its transaction before the bound commit and commits after it. The
    replay's answer is the original's snapshot — the outbox sequence as it stood when that commit
    returned — so the straggler is excluded however its start time and `recorded_at` compare.
    """
    declaration = _declare()
    key = _key_for(declaration)
    straggler = _declare(to_state="resolved", effective_at=T0 + timedelta(days=1))

    with psycopg.connect(host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"]) as second:
        second.execute("SELECT 1")  # the transaction is open from here
        first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
        commit_declaration(second, straggler)
        second.commit()

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert replay.event_id == first.event_id
    assert replay.outbox_seq == first.outbox_seq
    assert replay.state is not None
    assert replay.state.state == "received"
    # The straggler did land — which is what makes the assertions above load-bearing.
    assert len(_rows(ledger_db, "events")) == 2


# --- the race, deterministically and for real ---------------------------------------------------


def _blind_the_pre_check(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make the next call's binding lookup miss, as a writer racing an uncommitted winner would.

    Later lookups — the one the failed attempt forces — see the truth again, which is exactly the
    loser's recovery path.
    """
    real_settle = idempotency_module._settle
    calls: list[str] = []

    def _settle(conn: psycopg.Connection, key: str, binding: object) -> object:
        calls.append(key)
        return None if len(calls) == 1 else real_settle(conn, key, binding)  # type: ignore[arg-type]

    monkeypatch.setattr(idempotency_module, "_settle", _settle)
    return calls


def test_the_race_loser_rechecks_the_binding_before_returning_a_result(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The winner's result is not owed to whoever else claimed the key — it has to match first."""
    declaration = _declare()
    key = _key_for(declaration)
    commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    before = _counts(ledger_db)

    calls = _blind_the_pre_check(monkeypatch)
    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, _declare(writer=RECONCILIATION), idempotency_key=key, writer=RECONCILIATION)

    assert len(calls) == 2  # the blinded pre-check, then the recheck the failed attempt forced
    assert raised.value.reason == IDEMPOTENCY_CONFLICT
    # The losing attempt's event, state write and outbox row went with its savepoint.
    assert _counts(ledger_db) == before


def test_the_race_loser_with_a_matching_binding_is_still_replayed(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compatibility half of the same path: a genuine concurrent retry is owed the result."""
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    calls = _blind_the_pre_check(monkeypatch)
    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert len(calls) == 2
    assert (replay.replayed, replay.event_id) == (True, first.event_id)
    assert len(_rows(ledger_db, "events")) == 1


def _race(
    ledger_db: psycopg.Connection,
    pg_database: dict[str, str],
    attempts: list[tuple[Declaration, Writer]],
    key: str,
) -> tuple[list[CommitResult], list[BaseException]]:
    """Run each (declaration, writer) on its own connection, released together."""
    ready = threading.Barrier(len(attempts))
    results: list[CommitResult] = []
    failures: list[BaseException] = []
    guard = threading.Lock()

    def _attempt(conn: psycopg.Connection, declaration: Declaration, writer: Writer) -> None:
        try:
            ready.wait(timeout=10)
            result = commit_idempotent(conn, declaration, idempotency_key=key, writer=writer)
        except BaseException as failure:
            with guard:
                failures.append(failure)
        else:
            with guard:
                results.append(result)

    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as second:
        threads = [
            threading.Thread(target=_attempt, args=(conn, declaration, writer))
            for conn, (declaration, writer) in zip((ledger_db, second), attempts, strict=True)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads)
    return results, failures


@pytest.mark.critical
def test_two_connections_racing_the_same_request_commit_one_event_and_one_binding(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    declaration = _declare()
    key = _key_for(declaration)

    results, failures = _race(ledger_db, pg_database, [(declaration, RELAY), (declaration, RELAY)], key)

    assert failures == []
    assert len({result.event_id for result in results}) == 1
    assert sorted(result.replayed for result in results) == [False, True]
    assert _counts(ledger_db) == {"events": 1, "idempotency_keys": 1, "outbox": 1, "idempotency_bindings": 1}


@pytest.mark.critical
def test_two_connections_racing_different_requests_commit_one_and_reject_the_other(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """Same writer, two different requests under one key: one commits, the other is refused.

    The two differ in evidence, which the SDK's key does not hash and the fingerprint does — so
    both derive this one key honestly, and both are a legal genesis, which is what leaves the
    binding as the only thing that can separate them. Whichever loses — on the key's constraint, on
    the binding it finds, or on the validation that saw the winner's event — the ledger holds
    exactly the winner's four rows.
    """
    first = _declare(evidence={"rule_id": "r-1"})
    second = _declare(evidence={"rule_id": "r-2"})
    key = _key_for(first)
    assert key == _key_for(second)

    results, failures = _race(ledger_db, pg_database, [(first, RELAY), (second, RELAY)], key)

    assert len(results) == 1
    assert results[0].replayed is False
    assert [type(failure) for failure in failures] == [IdempotencyConflictError]
    assert _counts(ledger_db) == {"events": 1, "idempotency_keys": 1, "outbox": 1, "idempotency_bindings": 1}


@pytest.mark.critical
def test_two_writers_racing_the_same_key_commit_one_and_reject_the_other(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """Identical request text under two credentials. The key belongs to whoever claimed it."""
    key = _key_for(_declare())

    results, failures = _race(
        ledger_db,
        pg_database,
        [(_declare(), RELAY), (_declare(writer=RECONCILIATION), RECONCILIATION)],
        key,
    )

    assert len(results) == 1
    assert results[0].replayed is False
    assert [type(failure) for failure in failures] == [IdempotencyConflictError]
    assert _counts(ledger_db) == {"events": 1, "idempotency_keys": 1, "outbox": 1, "idempotency_bindings": 1}
    winner = _bindings(ledger_db)[0]
    assert winner[1] in {RELAY.writer_id, RECONCILIATION.writer_id}
    assert winner[4] == results[0].event_id


# --- under the role the service actually runs as -------------------------------------------------


def test_the_bound_path_runs_as_the_service_role(ledger_db: psycopg.Connection) -> None:
    """The role may append and read bindings and nothing else (migration 0006's grants)."""
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    declaration = _declare()
    key = _key_for(declaration)

    first = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    assert (replay.replayed, replay.event_id) == (True, first.event_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ledger_db.execute("DELETE FROM ledger.idempotency_bindings")
