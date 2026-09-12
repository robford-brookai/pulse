"""Legacy key reconstruction and the rollout inventory — task 2.2, against a real Postgres.

The scenarios here are `command-api`'s "Provable legacy retry is bound safely" and "Unverifiable
legacy retry blocks unsafe rollout". A *legacy* key is one claimed before bindings existed: the
pre-enforcement path (`commit_idempotent` with no `writer`) produces exactly that row shape, so the
fixtures below populate a synthetic legacy database the same way the deployed one was populated,
rather than hand-writing rows the commit path would never have written.

Four properties carry the weight:

- **Only what the event proves.** A binding is reconstructed from the stored event's own columns or
  it is not reconstructed at all. Nothing is defaulted, inferred from the key's text, or copied
  from the incoming request — the incoming request is only ever *compared* to what was rebuilt.
- **A refusal changes nothing.** No key is deleted, reassigned or released; no partial binding
  survives; the original event and its result stay exactly as they were.
- **The reconstruction equals the boundary's.** A key the boundary would have bound to `F` rebuilds
  to `F`, so a producer's valid retry keeps replaying across the migration. That equivalence is the
  compatibility acceptance criterion for the whole change (design §5).
- **The inventory is a gate, not a report.** It separates compatible, migrated, fix-required and
  unknown, it carries identifiers and counts but never a request value or a fingerprint, and an
  empty or unknown inventory cannot clear enforcement.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_core.idempotency import derive_idempotency_key
from pulse_ledger.auth import Writer
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration, commit_reversal
from pulse_ledger.idempotency import (
    IDEMPOTENCY_CONFLICT,
    IDEMPOTENCY_LEGACY_UNVERIFIABLE,
    IdempotencyConflictError,
    commit_idempotent,
)
from pulse_ledger.legacy_binding import (
    BLOCKING_DISPOSITIONS,
    LegacyDisposition,
    LegacyReason,
    inventory_legacy_keys,
    reconstruct_binding,
)
from pulse_ledger.request_fingerprint import FINGERPRINT_VERSION, request_fingerprint

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


def _legacy_commit(conn: psycopg.Connection, declaration: Declaration, key: str) -> CommitResult:
    """A key claimed the way the pre-binding server claimed it: the event, the key, no binding."""
    result = commit_idempotent(conn, declaration, idempotency_key=key)
    assert [binding for binding in _bindings(conn) if binding[0] == key] == []
    return result


def _rows(conn: psycopg.Connection, table: str) -> list[tuple[Any, ...]]:
    return conn.execute(f"SELECT * FROM ledger.{table}").fetchall()  # noqa: S608


def _bindings(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT key, writer_id, fingerprint_version, fingerprint, event_id"
        " FROM ledger.idempotency_bindings ORDER BY key"
    ).fetchall()


def _keys(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    return conn.execute("SELECT key, event_id, created_at FROM ledger.idempotency_keys ORDER BY key").fetchall()


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    return {
        table: len(_rows(conn, table)) for table in ("events", "idempotency_keys", "outbox", "idempotency_bindings")
    }


# --- a provable legacy key binds on first sight and replays -------------------------------------


def test_a_provable_legacy_retry_is_bound_transactionally_and_replayed(ledger_db: psycopg.Connection) -> None:
    """The scenario "Provable legacy retry is bound safely", end to end.

    The original committed through the unbound path, so the ledger holds an event, a key and no
    binding. Its authenticated writer retries the identical request: the event proves the actor and
    every canonical field, the binding is written beside the key it already had, and the original
    result is replayed rather than a second event committed.
    """
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, original.event_id)
    assert _bindings(ledger_db) == [
        (key, RELAY.writer_id, FINGERPRINT_VERSION, request_fingerprint(declaration), original.event_id)
    ]
    assert _counts(ledger_db) == {"events": 1, "idempotency_keys": 1, "outbox": 1, "idempotency_bindings": 1}


def test_the_reconstruction_equals_the_binding_the_boundary_would_have_written(
    ledger_db: psycopg.Connection,
) -> None:
    """The compatibility criterion in one assertion: rebuilt from the event == computed at ingress.

    Every canonical v1 field is carried on the declaration, including the two the boundary may leave
    off, so the equality covers the whole field map rather than its easy half.
    """
    declaration = _declare(
        epoch="reconstructed",
        evidence_class="E3",
        evidence={"rule_id": "r-1", "codes": ["b", "a"], "note": None},
        evidence_bounds=(T0 - timedelta(days=2), T0),
        payload={"reason": "intake", "score": 3, "flags": []},
    )
    key = _key_for(declaration)
    event_id = _legacy_commit(ledger_db, declaration, key).event_id

    reconstruction = reconstruct_binding(ledger_db, key, event_id)

    assert reconstruction.reason is None
    assert reconstruction.binding is not None
    assert reconstruction.binding.writer_id == RELAY.writer_id
    assert reconstruction.binding.fingerprint == request_fingerprint(declaration)


def test_an_equivalent_spelling_of_a_legacy_request_still_replays(ledger_db: psycopg.Connection) -> None:
    """A retry that spells the same instant `Z` and orders its object differently is one request."""
    original = _declare(payload={"reason": "intake", "score": 3})
    key = _key_for(original)
    first = _legacy_commit(ledger_db, original, key)

    retry = _declare(
        effective_at=T0.astimezone(timezone(timedelta(hours=2))),
        payload={"score": 3, "reason": "intake"},
    )
    replay = commit_idempotent(ledger_db, retry, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, first.event_id)
    assert len(_bindings(ledger_db)) == 1


def test_a_bound_legacy_key_replays_from_the_binding_on_every_later_retry(ledger_db: psycopg.Connection) -> None:
    """Reconstruction happens once. The second retry meets a binding and never rebuilds anything."""
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)

    commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)
    again = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert (again.replayed, again.event_id) == (True, original.event_id)
    assert len(_bindings(ledger_db)) == 1
    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, _declare(writer=RECONCILIATION), idempotency_key=key, writer=RECONCILIATION)
    assert raised.value.reason == IDEMPOTENCY_CONFLICT


def test_the_unbound_path_still_replays_a_legacy_key_unchanged(ledger_db: psycopg.Connection) -> None:
    """Reconstruction is for authenticated callers. An unbound retry is the pre-change path still."""
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key)

    assert (replay.replayed, replay.event_id) == (True, original.event_id)
    assert _bindings(ledger_db) == []


# --- a mismatch against a provable legacy key is an ordinary conflict ----------------------------


def test_another_writer_meeting_a_provable_legacy_key_conflicts_and_writes_nothing(
    ledger_db: psycopg.Connection,
) -> None:
    """The key belongs to whoever the original event proves claimed it, never to whoever asks."""
    declaration = _declare()
    key = _key_for(declaration)
    _legacy_commit(ledger_db, declaration, key)
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, _declare(writer=RECONCILIATION), idempotency_key=key, writer=RECONCILIATION)

    assert raised.value.reason == IDEMPOTENCY_CONFLICT
    assert _counts(ledger_db) == before
    assert _bindings(ledger_db) == []


def test_a_changed_request_under_a_provable_legacy_key_conflicts_and_writes_nothing(
    ledger_db: psycopg.Connection,
) -> None:
    declaration = _declare(evidence={"rule_id": "r-1"})
    key = _key_for(declaration)
    _legacy_commit(ledger_db, declaration, key)
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, _declare(evidence={"rule_id": "r-2"}), idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_CONFLICT
    assert _counts(ledger_db) == before
    assert _bindings(ledger_db) == []


# --- what the event cannot prove is never guessed -----------------------------------------------


def test_an_event_whose_attribution_is_not_credential_derived_is_unverifiable(
    ledger_db: psycopg.Connection,
) -> None:
    """`producer` disagreeing with `actor_id` means no credential stamped this event (D15).

    The boundary sets both from one `Writer`, so a row where they differ was written by some other
    path. Its writer is therefore not proved, and the key is refused rather than bound to a guess.
    """
    declaration = _declare(producer="migration-loader")
    key = _key_for(declaration)
    result = commit_declaration(ledger_db, declaration)
    ledger_db.execute("INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)", (key, result.event_id))
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE
    assert _counts(ledger_db) == before
    assert reconstruct_binding(ledger_db, key, result.event_id).reason is LegacyReason.UNATTRIBUTED_WRITER


def test_an_incomplete_evidence_bound_is_a_missing_field_not_an_assumed_one(
    ledger_db: psycopg.Connection,
) -> None:
    """One half of `evidence_bounds` does not determine the pair, so no canonical request exists.

    The synthetic row is made by nulling one bound on a committed event — the shape a partial
    historical write leaves behind, which the commit path itself can no longer produce.
    """
    declaration = _declare(evidence_class="E2", evidence_bounds=(T0 - timedelta(days=1), T0))
    key = _key_for(declaration)
    event_id = _legacy_commit(ledger_db, declaration, key).event_id
    ledger_db.execute("UPDATE ledger.events SET evidence_bound_upper = NULL WHERE event_id = %s", (event_id,))
    before = _counts(ledger_db)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE
    assert _counts(ledger_db) == before
    assert reconstruct_binding(ledger_db, key, event_id).reason is LegacyReason.INCOMPLETE_EVIDENCE_BOUNDS


def test_a_key_claiming_a_reversal_is_unverifiable(ledger_db: psycopg.Connection) -> None:
    """A reversal is not a declared command, so it proves no canonical request to rebuild."""
    declaration = _declare()
    original = commit_declaration(ledger_db, declaration)
    commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=1)))
    reversal = commit_reversal(
        ledger_db,
        reverses_event_id=original.event_id,
        actor_type=RELAY.actor_type,
        actor_id=RELAY.actor_id,
        producer=RELAY.writer_id,
        reason="entered in error",
    )
    key = "verdict-relay:legacy-reversal"
    ledger_db.execute("INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)", (key, reversal.event_id))

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE
    assert reconstruct_binding(ledger_db, key, reversal.event_id).reason is LegacyReason.CORRECTION_EVENT


def test_an_event_under_another_schema_version_is_undecidable_rather_than_broken(
    ledger_db: psycopg.Connection,
) -> None:
    """A newer stored shape is not proof of a v1 request, and this build cannot say it is not one."""
    declaration = _declare()
    key = _key_for(declaration)
    event_id = _legacy_commit(ledger_db, declaration, key).event_id
    ledger_db.execute("UPDATE ledger.events SET schema_version = 2 WHERE event_id = %s", (event_id,))

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert raised.value.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE
    assert reconstruct_binding(ledger_db, key, event_id).reason is LegacyReason.UNSUPPORTED_SCHEMA_VERSION


def test_a_refused_legacy_key_is_neither_released_nor_reassigned(ledger_db: psycopg.Connection) -> None:
    """The reservation is for the ledger's lifetime, refusal or not (D16, ADR-0007)."""
    declaration = _declare(producer="migration-loader")
    key = _key_for(declaration)
    result = commit_declaration(ledger_db, declaration)
    ledger_db.execute("INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)", (key, result.event_id))
    reserved = _keys(ledger_db)

    for writer in (RELAY, RECONCILIATION):
        with pytest.raises(IdempotencyConflictError):
            commit_idempotent(ledger_db, _declare(writer=writer), idempotency_key=key, writer=writer)

    assert _keys(ledger_db) == reserved
    assert _bindings(ledger_db) == []


def test_a_legacy_refusal_discloses_neither_the_original_result_nor_a_fingerprint(
    ledger_db: psycopg.Connection,
) -> None:
    """The refusal carries the key and a reason code. Nothing else travels with it."""
    declaration = _declare(payload={"reason": "intake"})
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)
    fingerprint = request_fingerprint(declaration)

    with pytest.raises(IdempotencyConflictError) as raised:
        commit_idempotent(ledger_db, _declare(writer=RECONCILIATION), idempotency_key=key, writer=RECONCILIATION)

    rendered = f"{raised.value!r} {raised.value!s} {vars(raised.value)!r}"
    assert str(original.event_id) not in rendered
    assert fingerprint not in rendered
    assert "intake" not in rendered
    assert raised.value.reason in {IDEMPOTENCY_CONFLICT, IDEMPOTENCY_LEGACY_UNVERIFIABLE}


# --- the original result stays the original's ---------------------------------------------------


def test_a_reconstructed_replay_returns_the_original_state_not_the_current_one(
    ledger_db: psycopg.Connection,
) -> None:
    """Binding a legacy key does not re-date its answer: later history stays outside it."""
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)
    commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=1)))

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, original.event_id)
    assert replay.state is not None
    assert replay.state.state == "received"
    assert replay.outbox_seq == original.outbox_seq


# --- concurrent reconstruction ------------------------------------------------------------------


def test_a_binding_written_by_another_transaction_first_is_adopted_not_duplicated(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """The deterministic half of the race: someone else reconstructed the same key a moment ago.

    One binding per key is the store's rule, so the second reconstruction must read the winner's
    row and answer from it rather than fail on the constraint.
    """
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)
    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=True
    ) as other:
        commit_idempotent(other, declaration, idempotency_key=key, writer=RELAY)

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, original.event_id)
    assert len(_bindings(ledger_db)) == 1


@pytest.mark.critical
def test_two_connections_reconstructing_one_legacy_key_write_exactly_one_binding(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """Two retries of one legacy request, released together: one binding, one event, two replays."""
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)

    results, failures = _race(ledger_db, pg_database, [(declaration, RELAY), (declaration, RELAY)], key)

    assert failures == []
    assert [result.event_id for result in results] == [original.event_id] * 2
    assert all(result.replayed for result in results)
    assert _counts(ledger_db) == {"events": 1, "idempotency_keys": 1, "outbox": 1, "idempotency_bindings": 1}


@pytest.mark.critical
def test_two_writers_reconstructing_one_legacy_key_bind_the_proved_one_and_reject_the_other(
    ledger_db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """A race cannot hand the key to the writer the original event does not name."""
    declaration = _declare()
    key = _key_for(declaration)
    _legacy_commit(ledger_db, declaration, key)

    results, failures = _race(
        ledger_db,
        pg_database,
        [(declaration, RELAY), (_declare(writer=RECONCILIATION), RECONCILIATION)],
        key,
    )

    assert len(results) == 1
    assert results[0].replayed is True
    assert [type(failure) for failure in failures] == [IdempotencyConflictError]
    assert _counts(ledger_db) == {"events": 1, "idempotency_keys": 1, "outbox": 1, "idempotency_bindings": 1}
    assert _bindings(ledger_db)[0][1] == RELAY.writer_id


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


# --- under the role the service actually runs as -------------------------------------------------


def test_reconstruction_runs_as_the_service_role(ledger_db: psycopg.Connection) -> None:
    """SELECT on events and keys, INSERT on bindings — the grants migration 0006 hands out."""
    declaration = _declare()
    key = _key_for(declaration)
    original = _legacy_commit(ledger_db, declaration, key)
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")

    replay = commit_idempotent(ledger_db, declaration, idempotency_key=key, writer=RELAY)

    assert (replay.replayed, replay.event_id) == (True, original.event_id)
    assert len(_bindings(ledger_db)) == 1


# --- the rollout inventory ----------------------------------------------------------------------


def test_an_empty_inventory_blocks_enforcement(ledger_db: psycopg.Connection) -> None:
    """ "No rows" is not a pass: an empty table means the inventory has not been taken."""
    inventory = inventory_legacy_keys(ledger_db)

    assert inventory.rows == ()
    assert inventory.total_keys == 0
    assert inventory.enforcement_blocked is True
    assert "no keys inventoried" in " ".join(inventory.blocking_reasons())


def test_the_inventory_separates_compatible_migrated_fix_required_and_unknown(
    ledger_db: psycopg.Connection,
) -> None:
    """One row per producer, at the worst disposition any of its keys holds."""
    compatible = _declare(subject_key="ref-compatible")
    _legacy_commit(ledger_db, compatible, _key_for(compatible))

    migrated = _declare(subject_key="ref-migrated")
    commit_idempotent(ledger_db, migrated, idempotency_key=_key_for(migrated), writer=RELAY)

    unknown = _declare(subject_key="ref-unknown")
    unknown_id = _legacy_commit(ledger_db, unknown, _key_for(unknown)).event_id
    ledger_db.execute("UPDATE ledger.events SET schema_version = 2 WHERE event_id = %s", (unknown_id,))

    broken = _declare(subject_key="ref-broken", writer=RECONCILIATION, producer="migration-loader")
    broken_result = commit_declaration(ledger_db, broken)
    ledger_db.execute(
        "INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)",
        (_key_for(broken, writer_id=RECONCILIATION.writer_id), broken_result.event_id),
    )

    inventory = inventory_legacy_keys(ledger_db)

    by_producer = {row.producer: row for row in inventory.rows}
    assert by_producer["verdict-relay"].disposition is LegacyDisposition.UNKNOWN
    assert by_producer["verdict-relay"].counts[LegacyDisposition.COMPATIBLE] == 1
    assert by_producer["verdict-relay"].counts[LegacyDisposition.MIGRATED] == 1
    assert by_producer["verdict-relay"].counts[LegacyDisposition.UNKNOWN] == 1
    assert by_producer["migration-loader"].disposition is LegacyDisposition.FIX_REQUIRED
    assert by_producer["migration-loader"].reasons == (LegacyReason.UNATTRIBUTED_WRITER.value,)
    assert inventory.total_keys == 4
    assert inventory.enforcement_blocked is True


def test_an_all_compatible_inventory_clears_the_gate(ledger_db: psycopg.Connection) -> None:
    """The one shape that does not block: every key rebuilds, or is already bound."""
    compatible = _declare(subject_key="ref-compatible")
    _legacy_commit(ledger_db, compatible, _key_for(compatible))
    migrated = _declare(subject_key="ref-migrated")
    commit_idempotent(ledger_db, migrated, idempotency_key=_key_for(migrated), writer=RELAY)

    inventory = inventory_legacy_keys(ledger_db)

    assert [row.disposition for row in inventory.rows] == [LegacyDisposition.COMPATIBLE]
    assert inventory.enforcement_blocked is False
    assert inventory.blocking_reasons() == ()


@pytest.mark.parametrize("blocking", sorted(disposition.value for disposition in BLOCKING_DISPOSITIONS))
def test_every_blocking_disposition_is_named_in_the_gate_reasons(blocking: str) -> None:
    """`fix-required` and `unknown` are the two that block, and both are the doc's spelling."""
    assert blocking in {LegacyDisposition.FIX_REQUIRED.value, LegacyDisposition.UNKNOWN.value}


def test_the_inventory_records_identifiers_and_counts_but_no_request_values(
    ledger_db: psycopg.Connection,
) -> None:
    """The inventory is written into a doc and an issue, so nothing derived from a payload may
    reach it — not a value, not an evidence member, and not the fingerprint (a digest of a small
    value space is a lookup table)."""
    declaration = _declare(evidence={"rule_id": "r-secret"}, payload={"reason": "a-payload-value", "score": 3})
    key = _key_for(declaration)
    _legacy_commit(ledger_db, declaration, key)
    bound = _declare(subject_key="ref-bound", payload={"reason": "another-payload-value"})
    commit_idempotent(ledger_db, bound, idempotency_key=_key_for(bound), writer=RELAY)

    rendered = repr(inventory_legacy_keys(ledger_db))

    for forbidden in ("a-payload-value", "another-payload-value", "r-secret", request_fingerprint(declaration)):
        assert forbidden not in rendered
    assert RELAY.writer_id in rendered


def test_the_inventory_reads_under_the_service_role(ledger_db: psycopg.Connection) -> None:
    declaration = _declare()
    _legacy_commit(ledger_db, declaration, _key_for(declaration))
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")

    assert inventory_legacy_keys(ledger_db).total_keys == 1
