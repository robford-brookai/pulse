"""Idempotent commit — task 3.3's two spec scenarios, against a real Postgres.

1. **Retry after timeout is a replay**: the same key twice yields one event, and the second call
   returns the first event's id marked as a replay.
2. **Distinct facts never share a key**: the same writer, subject and command at a new
   `logical_time` derives a different key and commits a second event.

Both scenarios are driven through `pulse_core.derive_idempotency_key`, so the two halves of D16 —
the client's derivation and the ledger's unique constraint — are tested as the one mechanism they
are. The rest covers what stands between them: the key row is claimed in the commit's own
transaction, a rejected command burns no key, and a duplicate that slips past the pre-check is
absorbed by the constraint rather than becoming a second event.
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
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration, commit_reversal
from pulse_ledger.idempotency import MissingOutboxRowError, commit_idempotent
from pulse_ledger.validation import IllegalTransitionError

SERVICE_ROLE = "pulse_ledger_service"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _declare(
    subject_type: str = "referral",
    subject_key: str = "ref-1",
    to_state: str = "received",
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
        "actor_id": "verdict-relay",
        "producer": "pulse-ledger-tests",
    }
    fields.update(overrides)
    return Declaration(**fields)


def _key_for(
    declaration: Declaration, *, writer_id: str = "verdict-relay", logical_time: datetime | None = None
) -> str:
    """The key a writer would derive for this declaration, the way the client SDK derives it."""
    return derive_idempotency_key(
        writer_id=writer_id,
        subject_type=declaration.subject_type,
        subject_key=declaration.subject_key,
        command_type="declare_transition",
        payload=dict(declaration.event_payload()),
        logical_time=logical_time or declaration.effective_at,
    )


def _rows(conn: psycopg.Connection, table: str) -> list[tuple[Any, ...]]:
    return conn.execute(f"SELECT * FROM ledger.{table}").fetchall()  # noqa: S608


def _keys(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    return conn.execute("SELECT key, event_id FROM ledger.idempotency_keys ORDER BY key").fetchall()


# --- scenario: retry after timeout is a replay -------------------------------------------------


def test_a_retry_with_the_same_key_replays_the_original_commit_and_writes_no_second_event(
    ledger_db: psycopg.Connection,
) -> None:
    declaration = _declare()
    key = _key_for(declaration)

    first = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    assert first.replayed is False

    # The writer never saw the response and sends the identical command again.
    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key)

    assert replay.replayed is True
    assert replay.event_id == first.event_id
    assert replay.recorded_at == first.recorded_at
    assert replay.rule_version == first.rule_version
    assert replay.outbox_seq == first.outbox_seq
    assert replay.state == first.state

    # Exactly one event, one state row, one outbox row, one key.
    assert len(_rows(ledger_db, "events")) == 1
    assert len(_rows(ledger_db, "current_state")) == 1
    assert len(_rows(ledger_db, "outbox")) == 1
    assert _keys(ledger_db) == [(key, first.event_id)]


def test_the_key_row_maps_the_key_to_the_event_it_committed(ledger_db: psycopg.Connection) -> None:
    declaration = _declare()
    key = _key_for(declaration)
    result = commit_idempotent(ledger_db, declaration, idempotency_key=key)

    stored = ledger_db.execute(
        "SELECT event_id, created_at FROM ledger.idempotency_keys WHERE key = %s", (key,)
    ).fetchone()
    assert stored is not None
    event_id, created_at = stored
    assert event_id == result.event_id
    assert created_at is not None


def test_a_replay_reports_the_state_the_original_commit_produced_not_the_subjects_state_now(
    ledger_db: psycopg.Connection,
) -> None:
    """A replay answers the command it repeats. The subject may have moved on since."""
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    later = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=1)))

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    assert replay.state is not None
    assert replay.state.state == "received"
    assert replay.state.event_id == first.event_id

    # The store itself has moved on, which is what makes the assertion above load-bearing.
    assert ledger_db.execute("SELECT last_event_id FROM ledger.current_state").fetchone() == (later.event_id,)


def test_a_replay_of_an_event_that_was_later_reversed_still_returns_that_event(
    ledger_db: psycopg.Connection,
) -> None:
    """The key is claimed forever (D16): a reversal corrects state, it does not free the key."""
    commit_declaration(ledger_db, _declare())
    mistake_declaration = _declare(to_state="closed", effective_at=T0 + timedelta(days=1))
    key = _key_for(mistake_declaration)
    mistake = commit_idempotent(ledger_db, mistake_declaration, idempotency_key=key)
    commit_reversal(
        ledger_db,
        reverses_event_id=mistake.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-tests",
        reason="closed_in_error",
    )

    replay = commit_idempotent(ledger_db, mistake_declaration, idempotency_key=key)
    assert (replay.replayed, replay.event_id) == (True, mistake.event_id)
    # Three events: the genesis, the mistake, the reversal. The retry added none.
    assert len(_rows(ledger_db, "events")) == 3


# --- scenario: distinct facts never share a key ------------------------------------------------


def test_the_same_command_at_a_new_logical_time_commits_a_second_event(ledger_db: psycopg.Connection) -> None:
    first_declaration = _declare(subject_type="billing_episode", subject_key="be-1", to_state="open")
    second_declaration = _declare(
        subject_type="billing_episode",
        subject_key="be-1",
        to_state="qualified",
        effective_at=T0 + timedelta(days=1),
    )
    first_key = _key_for(first_declaration)
    second_key = _key_for(second_declaration)
    assert first_key != second_key

    first = commit_idempotent(ledger_db, first_declaration, idempotency_key=first_key)
    second = commit_idempotent(ledger_db, second_declaration, idempotency_key=second_key)

    assert (first.replayed, second.replayed) == (False, False)
    assert first.event_id != second.event_id
    assert len(_rows(ledger_db, "events")) == 2
    assert (first.outbox_seq, second.outbox_seq) == (1, 2)
    assert _keys(ledger_db) == sorted([(first_key, first.event_id), (second_key, second.event_id)])


def test_one_writers_command_is_never_answered_by_anothers_key(ledger_db: psycopg.Connection) -> None:
    """The writer id is part of the key, so a second writer's identical command is not a replay.

    It reaches the ledger on its own merits — and here the ledger rejects it, because `received` is
    already the subject's state and the catalog has no self-loop. What matters is that it was
    judged rather than silently answered with the first writer's event.
    """
    declaration = _declare()
    relay_key = _key_for(declaration, writer_id="verdict-relay")
    reconciliation_key = _key_for(declaration, writer_id="reconciliation")
    assert relay_key != reconciliation_key

    commit_idempotent(ledger_db, declaration, idempotency_key=relay_key)
    with pytest.raises(IllegalTransitionError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=reconciliation_key)
    assert raised.value.from_state == "received"

    assert len(_rows(ledger_db, "events")) == 1
    assert [key for key, _ in _keys(ledger_db)] == [relay_key]


# --- the key is claimed in the commit's own transaction ----------------------------------------


def test_a_rejected_command_claims_no_key(ledger_db: psycopg.Connection) -> None:
    """A rejection must not burn the key: the writer's corrected retry has to be able to commit."""
    illegal = _declare(to_state="outreach")
    key = _key_for(illegal)
    with pytest.raises(IllegalTransitionError):
        commit_idempotent(ledger_db, illegal, idempotency_key=key)

    assert _rows(ledger_db, "events") == []
    assert _keys(ledger_db) == []


def test_an_injected_failure_after_the_key_claim_leaves_neither_the_key_nor_the_event(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    injected = RuntimeError("connection dropped before commit")
    real_claim = idempotency_module._claim

    def _claim_then_fail(conn: psycopg.Connection, key: str, event_id: uuid.UUID) -> None:
        real_claim(conn, key, event_id)
        raise injected

    monkeypatch.setattr(idempotency_module, "_claim", _claim_then_fail)
    declaration = _declare()
    key = _key_for(declaration)
    with pytest.raises(RuntimeError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key)
    assert raised.value is injected

    assert _rows(ledger_db, "events") == []
    assert _rows(ledger_db, "current_state") == []
    assert _rows(ledger_db, "outbox") == []
    assert _keys(ledger_db) == []

    # And the key is free, so the writer's retry commits rather than replaying a phantom.
    monkeypatch.undo()
    result = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    assert result.replayed is False


def test_the_idempotent_path_runs_as_the_service_role(ledger_db: psycopg.Connection) -> None:
    """The role may INSERT and SELECT keys and nothing else — no UPDATE, no DELETE (D16)."""
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    assert (replay.replayed, replay.event_id) == (True, first.event_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ledger_db.execute("DELETE FROM ledger.idempotency_keys")


# --- the constraint, for what the pre-check cannot see ------------------------------------------


def _blind_the_pre_check(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make the next call's key lookup miss, as a writer racing an uncommitted winner would.

    Later lookups — the one the failed attempt forces — see the truth again.
    """
    real_lookup = idempotency_module._replay_of
    lookups: list[str] = []

    def _lookup(conn: psycopg.Connection, lookup_key: str) -> object:
        lookups.append(lookup_key)
        return None if len(lookups) == 1 else real_lookup(conn, lookup_key)

    monkeypatch.setattr(idempotency_module, "_replay_of", _lookup)
    return lookups


def test_a_key_reused_for_a_different_fact_is_absorbed_by_the_unique_constraint(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The constraint, not the pre-check, is what makes the key unique for the ledger's lifetime.

    A writer reusing a key for a genuinely different fact is answered with the fact the key already
    holds, and its second fact is not written — the key is the promise, and it was already kept.
    """
    first_declaration = _declare()
    key = _key_for(first_declaration)
    first = commit_idempotent(ledger_db, first_declaration, idempotency_key=key)

    lookups = _blind_the_pre_check(monkeypatch)
    # A legal transition on its own merits, so only the key's constraint can stop it.
    replay = commit_idempotent(
        ledger_db,
        _declare(to_state="resolved", effective_at=T0 + timedelta(days=1)),
        idempotency_key=key,
    )

    assert len(lookups) == 2  # the blinded pre-check, then the lookup the violation forced
    assert (replay.replayed, replay.event_id) == (True, first.event_id)
    assert replay.outbox_seq == first.outbox_seq
    assert replay.state is not None
    assert replay.state.state == "received"
    # The event, state write and outbox row the losing attempt made went with its savepoint.
    assert len(_rows(ledger_db, "events")) == 1
    assert len(_rows(ledger_db, "outbox")) == 1
    assert ledger_db.execute("SELECT state FROM ledger.current_state").fetchone() == ("received",)


def test_a_concurrent_duplicate_is_replayed_even_though_it_fails_validation_first(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loser of a race does not usually reach the key insert, and must still be replayed.

    Its per-subject advisory lock is released only when the winner's transaction commits, so it
    folds the winner's event into its own validation and finds its declaration illegal — no state
    in the catalog has a self-loop. That rejection is not the writer's answer: the key is claimed,
    so the command is committed and the writer is owed the winner's event id.
    """
    declaration = _declare()
    key = _key_for(declaration)
    first = commit_idempotent(ledger_db, declaration, idempotency_key=key)

    lookups = _blind_the_pre_check(monkeypatch)
    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key)

    assert len(lookups) == 2
    assert (replay.replayed, replay.event_id) == (True, first.event_id)
    assert len(_rows(ledger_db, "events")) == 1


def test_the_same_key_arriving_twice_at_once_still_produces_one_event(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """The race the two tests above simulate, run for real on two connections.

    Whichever attempt loses — on the key's constraint or on the validation that saw the winner's
    event — both writers come away with the same event id and the ledger holds one event. If the
    two happen not to overlap the assertions are the plain pre-check path, so this cannot flake.
    """
    declaration = _declare()
    key = _key_for(declaration)
    ready = threading.Barrier(2)
    results: list[CommitResult] = []
    failures: list[BaseException] = []
    guard = threading.Lock()

    def _attempt(conn: psycopg.Connection) -> None:
        try:
            ready.wait(timeout=10)
            result = commit_idempotent(conn, declaration, idempotency_key=key)
        except BaseException as failure:
            with guard:
                failures.append(failure)
        else:
            with guard:
                results.append(result)

    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as second:
        threads = [threading.Thread(target=_attempt, args=(conn,)) for conn in (ledger_db, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads)

    assert failures == []
    assert len(results) == 2
    assert len({result.event_id for result in results}) == 1
    assert sorted(result.replayed for result in results) == [False, True]
    assert len(_rows(ledger_db, "events")) == 1
    assert len(_keys(ledger_db)) == 1


def test_a_fault_in_the_attempt_is_not_mistaken_for_a_replay(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A claimed key means replay. A failure with no claimed key is the writer's answer."""
    commit_declaration(ledger_db, _declare())

    def _collide(conn: psycopg.Connection, event_id: uuid.UUID, subject_type: str, subject_key: str) -> int:
        conn.execute(
            "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq) VALUES (%s, %s, %s, 1)",
            (event_id, subject_type, subject_key),
        )
        return 1

    monkeypatch.setattr("pulse_ledger.commit._insert_outbox_row", _collide)
    declaration = _declare(to_state="resolved", effective_at=T0 + timedelta(days=1))
    with pytest.raises(psycopg.errors.UniqueViolation) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=_key_for(declaration))
    assert raised.value.diag.constraint_name == "uq_outbox_subject_seq"


def test_a_key_whose_outbox_row_has_gone_missing_is_reported_not_papered_over(
    ledger_db: psycopg.Connection,
) -> None:
    """The outbox row is co-committed and nothing in the schema removes it.

    If a future relay prunes published rows, a replay can no longer report the seq the original
    commit assigned. That is an invariant breach, and it says so rather than inventing a number or
    surfacing as a confusing duplicate-key error.
    """
    declaration = _declare()
    key = _key_for(declaration)
    result = commit_idempotent(ledger_db, declaration, idempotency_key=key)
    ledger_db.execute("DELETE FROM ledger.outbox WHERE event_id = %s", (result.event_id,))

    with pytest.raises(MissingOutboxRowError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key)
    assert raised.value.event_id == result.event_id
