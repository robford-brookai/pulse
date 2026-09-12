"""Migration 0006 — the companion binding table (idempotency-integrity 1.2).

ADR-0007 amends D16: a key is answerable only by the writer that claimed it, with the request that
claimed it. 1.1 defined both halves as values (`pulse_ledger.request_fingerprint`); this migration
gives them a place to live, and this suite asserts the store enforces what the commit path (2.1)
will rely on rather than re-checking in Python:

- an additive upgrade over a *populated* pre-binding schema leaves every legacy row alone —
  events, keys, folded state and undelivered relay rows — and the lifetime global key reservation
  keeps working afterwards;
- a binding cannot name an event its own key did not claim, nor one the ledger does not hold — the
  composite foreign key makes "the binding's event" and "the key's event" the same fact, not two
  that must agree;
- a fingerprint carries its version, and the version column and the digest prefix cannot disagree;
- a key is bound once: a second binding, under the same writer or another, is refused;
- the service role may read and append bindings and may UPDATE, DELETE or TRUNCATE none of the
  three retained relations (bindings, keys, events), and a TRUNCATE grant an earlier deploy handed
  out is taken back when the migration runs;
- the rollback preserves data — the service loses access, every binding row, key and event
  survives, and going forward again restores access over the retained rows, repeatedly;
- a binding insert that fails takes the proposed event, key claim and relay row down with it, and
  another connection never observes a partial claim.

Every fingerprint here is produced by the real v1 producer (`bind_request` over
`declaration_from_request`), so the store's format constraint is tested against what the boundary
will actually store. Fixtures are synthetic: invented `enrollment` keys, never a real patient.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from pulse_ledger.api import declaration_from_request
from pulse_ledger.auth import Writer
from pulse_ledger.request_fingerprint import FINGERPRINT_VERSION, bind_request

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"

SERVICE_ROLE = "pulse_ledger_service"

#: The revision 0006 is additive over — the schema every deployed ledger is at today.
PRE_BINDING = "0005"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

CONNECTOR = Writer(writer_id="clinic-connector", actor_authority="connector")
OTHER_WRITER = Writer(writer_id="reconciliation")

SUBJECT_KEY = "enrollment-synthetic-0001"


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(_alembic_config(database_url), revision)


def _downgrade(database_url: str, revision: str) -> None:
    command.downgrade(_alembic_config(database_url), revision)


def _request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "subject_type": "enrollment",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_transition",
        "to_state": "on_hold",
        "effective_at": "2026-08-03T11:59:00+00:00",
        "payload": {"hold_reason": "awaiting_authorization"},
    }
    request.update(overrides)
    return request


def _fingerprint(writer: Writer = CONNECTOR, **overrides: Any) -> str:
    """A real v1 fingerprint, through the same boundary the commit path will use."""
    binding = bind_request(
        idempotency_key="unused",
        writer=writer,
        declaration=declaration_from_request(_request(**overrides), writer),
    )
    return binding.fingerprint


def _insert_event(conn: psycopg.Connection, subject_key: str = SUBJECT_KEY) -> uuid.UUID:
    event_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO ledger.events (event_id, subject_type, subject_key, event_type, effective_at,"
        " producer, rule_version, actor_type, actor_id)"
        " VALUES (%s, 'enrollment', %s, 'declare_transition', %s, 'migration-tests', '1.1.0',"
        " 'system', 'clinic-connector')",
        (event_id, subject_key, T0),
    )
    return event_id


def _claim_key(conn: psycopg.Connection, key: str, event_id: uuid.UUID) -> None:
    conn.execute("INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)", (key, event_id))


def _enqueue(conn: psycopg.Connection, event_id: uuid.UUID, *, subject_key: str = SUBJECT_KEY, seq: int = 1) -> None:
    """The relay row a commit writes beside its event (D17) — part of the same transaction."""
    conn.execute(
        "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq) VALUES (%s, 'enrollment', %s, %s)",
        (event_id, subject_key, seq),
    )


def _insert_binding(
    conn: psycopg.Connection,
    *,
    key: str,
    event_id: uuid.UUID,
    writer_id: str = CONNECTOR.writer_id,
    fingerprint: str | None = None,
    fingerprint_version: str | None = None,
) -> None:
    digest = _fingerprint() if fingerprint is None else fingerprint
    version = digest.partition(":")[0] if fingerprint_version is None else fingerprint_version
    conn.execute(
        "INSERT INTO ledger.idempotency_bindings (key, writer_id, fingerprint_version, fingerprint, event_id)"
        " VALUES (%s, %s, %s, %s, %s)",
        (key, writer_id, version, digest, event_id),
    )


def _claim(conn: psycopg.Connection, key: str, **binding: Any) -> uuid.UUID:
    """One whole claim: the event, its key and its binding, as the commit path will write them."""
    event_id = _insert_event(conn)
    _claim_key(conn, key, event_id)
    _insert_binding(conn, key=key, event_id=event_id, **binding)
    return event_id


@contextmanager
def _as_service_role(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """`conn` acting as the ledger service role, reset afterwards.

    A context manager rather than a fixture: the role is created by migration 0001, so it does not
    exist until a test has run its own upgrade.
    """
    conn.execute(f"SET ROLE {SERVICE_ROLE}")
    try:
        yield conn
    finally:
        conn.execute("RESET ROLE")


def _rows(conn: psycopg.Connection, statement: str) -> list[tuple[Any, ...]]:
    return list(conn.execute(statement).fetchall())


def _has_privilege(conn: psycopg.Connection, table: str, privilege: str) -> bool:
    """Whether the service role holds one privilege on one `ledger` table."""
    cur = conn.execute(
        "SELECT has_table_privilege(%s, %s, %s)",
        (SERVICE_ROLE, f"ledger.{table}", privilege),
    )
    return bool(cur.fetchone()[0])


def _binding_constraints(conn: psycopg.Connection) -> set[str]:
    """Every constraint the binding table carries, by name."""
    cur = conn.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'ledger.idempotency_bindings'::regclass")
    return {name for (name,) in cur.fetchall()}


@pytest.mark.critical
def test_a_populated_pre_binding_schema_upgrades_without_changing_legacy_rows(
    database_url: str, db: psycopg.Connection
) -> None:
    """The expand step of the rollout, over a ledger that already holds keyed events."""
    _upgrade(database_url, PRE_BINDING)
    legacy_event = _insert_event(db, "enrollment-legacy-0001")
    legacy_key = "some-prefix:" + "b" * 64
    _claim_key(db, legacy_key, legacy_event)
    db.execute(
        "INSERT INTO ledger.current_state (subject_type, subject_key, state, effective_at, last_event_id)"
        " VALUES ('enrollment', 'enrollment-legacy-0001', 'on_hold', %s, %s)",
        (T0, legacy_event),
    )
    _enqueue(db, legacy_event, subject_key="enrollment-legacy-0001")
    events_before = _rows(db, "SELECT * FROM ledger.events ORDER BY event_id")
    keys_before = _rows(db, "SELECT * FROM ledger.idempotency_keys ORDER BY key")
    state_before = _rows(db, "SELECT * FROM ledger.current_state ORDER BY subject_key")
    outbox_before = _rows(db, "SELECT * FROM ledger.outbox ORDER BY event_id")

    _upgrade(database_url)

    assert _rows(db, "SELECT * FROM ledger.events ORDER BY event_id") == events_before
    assert _rows(db, "SELECT * FROM ledger.idempotency_keys ORDER BY key") == keys_before
    assert _rows(db, "SELECT * FROM ledger.current_state ORDER BY subject_key") == state_before
    # An undelivered relay row is mid-flight work, not history: the upgrade must not disturb it.
    assert _rows(db, "SELECT * FROM ledger.outbox ORDER BY event_id") == outbox_before
    # The legacy key is unbound, not migrated: deriving its binding is task 2.2's work, and
    # guessing one here is exactly what ADR-0007 forbids.
    assert _rows(db, "SELECT * FROM ledger.idempotency_bindings") == []


@pytest.mark.critical
def test_the_lifetime_global_key_reservation_survives_the_upgrade(database_url: str, db: psycopg.Connection) -> None:
    """D16's reservation is not re-namespaced by the binding: one key text, one claim, forever."""
    _upgrade(database_url, PRE_BINDING)
    legacy_event = _insert_event(db, "enrollment-legacy-0002")
    key = "some-prefix:" + "c" * 64
    _claim_key(db, key, legacy_event)

    _upgrade(database_url)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _claim_key(db, key, _insert_event(db))


def test_a_binding_records_its_writer_event_and_versioned_fingerprint(
    database_url: str, db: psycopg.Connection
) -> None:
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "d" * 64
    event_id = _claim(db, key)

    stored = db.execute(
        "SELECT writer_id, fingerprint_version, fingerprint, event_id FROM ledger.idempotency_bindings WHERE key = %s",
        (key,),
    ).fetchone()
    assert stored == (CONNECTOR.writer_id, FINGERPRINT_VERSION, _fingerprint(), event_id)


@pytest.mark.critical
def test_a_binding_cannot_reference_an_event_its_key_did_not_claim(database_url: str, db: psycopg.Connection) -> None:
    """The integrity the replay path depends on: the binding's event *is* the key's event."""
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "e" * 64
    _claim_key(db, key, _insert_event(db))
    other_event = _insert_event(db, "enrollment-synthetic-0002")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_binding(db, key=key, event_id=other_event)
    # And an event the ledger does not hold at all — a dangling reference is refused by the same
    # constraint, so there is no shape of wrong event the binding can record.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_binding(db, key=key, event_id=uuid.uuid4())


def test_a_binding_requires_a_claimed_key(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_binding(db, key="never-claimed:" + "f" * 64, event_id=_insert_event(db))


def test_a_fingerprint_carries_a_version_that_matches_its_column(database_url: str, db: psycopg.Connection) -> None:
    """Explicit version integrity: an unversioned digest and a mislabelled one are both refused."""
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "1" * 64
    event_id = _insert_event(db)
    _claim_key(db, key, event_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_binding(db, key=key, event_id=event_id, fingerprint="0" * 64, fingerprint_version="v1")
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_binding(db, key=key, event_id=event_id, fingerprint_version="v2")
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_binding(db, key=key, event_id=event_id, writer_id="   ")

    # The real producer's spelling is the one the constraint admits.
    _insert_binding(db, key=key, event_id=event_id)


@pytest.mark.critical
def test_a_key_is_bound_once_and_never_rebound(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "2" * 64
    event_id = _claim(db, key)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_binding(db, key=key, event_id=event_id)
    # Another writer claiming the same key is the disclosure channel ADR-0007 closes; the store
    # refuses it before any application check runs.
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_binding(db, key=key, event_id=event_id, writer_id=OTHER_WRITER.writer_id)


@pytest.mark.critical
def test_the_service_role_may_append_bindings_but_mutate_nothing_retained(
    database_url: str, db: psycopg.Connection
) -> None:
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "3" * 64
    with _as_service_role(db) as service:
        event_id = _claim(service, key)

        for statement in (
            "UPDATE ledger.idempotency_bindings SET writer_id = 'someone-else'",
            "DELETE FROM ledger.idempotency_bindings",
            "UPDATE ledger.idempotency_keys SET event_id = gen_random_uuid()",
            "DELETE FROM ledger.idempotency_keys",
            "UPDATE ledger.events SET subject_key = 'tampered'",
            "DELETE FROM ledger.events",
            # TRUNCATE is the third way to lose a retained row, and it is not covered by the
            # DELETE revoke.
            "TRUNCATE ledger.idempotency_bindings",
            "TRUNCATE ledger.idempotency_keys",
            "TRUNCATE ledger.events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                service.execute(statement)

        stored = service.execute("SELECT event_id FROM ledger.idempotency_bindings WHERE key = %s", (key,)).fetchone()
        assert stored == (event_id,)


@pytest.mark.critical
def test_the_migration_removes_an_existing_service_truncate_grant(database_url: str, db: psycopg.Connection) -> None:
    """The revokes are executed, not assumed: a grant an earlier deploy handed out is taken back.

    They do not immunise the tables — a later `GRANT` reopens access until a migration runs again —
    so what is asserted here is removal on run, not permanence.
    """
    _upgrade(database_url, PRE_BINDING)
    for table in ("idempotency_keys", "events"):
        db.execute(f"GRANT TRUNCATE ON ledger.{table} TO {SERVICE_ROLE}")
    assert _has_privilege(db, "idempotency_keys", "TRUNCATE")

    _upgrade(database_url)

    for table in ("idempotency_bindings", "idempotency_keys", "events"):
        for privilege in ("TRUNCATE", "UPDATE", "DELETE"):
            assert not _has_privilege(db, table, privilege), f"{privilege} on {table}"
    assert _has_privilege(db, "idempotency_bindings", "INSERT")


@pytest.mark.critical
def test_downgrade_preserves_bindings_keys_and_events(database_url: str, db: psycopg.Connection) -> None:
    """The rollback preserves data: the service loses access, the retained rows stay (ADR-0007)."""
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "4" * 64
    event_id = _claim(db, key)
    bindings_before = _rows(db, "SELECT * FROM ledger.idempotency_bindings ORDER BY key")

    _downgrade(database_url, PRE_BINDING)

    assert _rows(db, "SELECT * FROM ledger.idempotency_bindings ORDER BY key") == bindings_before
    assert db.execute("SELECT event_id FROM ledger.idempotency_keys WHERE key = %s", (key,)).fetchone() == (event_id,)
    assert db.execute("SELECT 1 FROM ledger.events WHERE event_id = %s", (event_id,)).fetchone() == (1,)

    # The service is back to its 0005 privilege set: the table it can no longer write is also one
    # it can no longer read.
    with _as_service_role(db) as service, pytest.raises(psycopg.errors.InsufficientPrivilege):
        service.execute("SELECT 1 FROM ledger.idempotency_bindings")


def test_repeated_round_trips_preserve_contents_and_constraints(database_url: str, db: psycopg.Connection) -> None:
    """Re-upgrading after a rollback is the supported path forward, not a fresh start.

    Run twice, because the retained table is exactly what a naive second upgrade would trip over.
    """
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "5" * 64
    event_id = _claim(db, key)
    constraints = _binding_constraints(db)
    assert constraints, "the binding table carries constraints to preserve"

    for cycle in range(2):
        _downgrade(database_url, PRE_BINDING)
        _upgrade(database_url)

        assert db.execute("SELECT event_id FROM ledger.idempotency_bindings WHERE key = %s", (key,)).fetchone() == (
            event_id,
        ), f"cycle {cycle}"
        assert _binding_constraints(db) == constraints, f"cycle {cycle}"
        # Access is back, over the retained rows rather than beside them.
        with _as_service_role(db) as service:
            _claim(service, f"{CONNECTOR.writer_id}:{cycle}" + "6" * 63)

    assert db.execute("SELECT count(*) FROM ledger.idempotency_bindings").fetchone() == (3,)


@pytest.mark.critical
def test_a_failed_binding_insert_rolls_back_the_whole_claim(
    database_url: str, db: psycopg.Connection, pg_database: dict[str, str]
) -> None:
    """Event, key and binding commit together or not at all — and no other connection sees the
    in-flight claim, so a race loser never reads a partial one."""
    _upgrade(database_url)
    key = f"{CONNECTOR.writer_id}:" + "7" * 64
    other_event = _insert_event(db, "enrollment-synthetic-0003")

    with psycopg.connect(
        host=pg_database["host"], user=pg_database["user"], dbname=pg_database["dbname"], autocommit=False
    ) as writer_conn:
        event_id = _insert_event(writer_conn)
        _claim_key(writer_conn, key, event_id)
        _enqueue(writer_conn, event_id)
        # Nothing is observable from another connection while the claim is in flight — including
        # the relay row, which would otherwise publish an event that never committed.
        assert db.execute("SELECT 1 FROM ledger.events WHERE event_id = %s", (event_id,)).fetchone() is None
        assert db.execute("SELECT 1 FROM ledger.idempotency_keys WHERE key = %s", (key,)).fetchone() is None
        assert db.execute("SELECT 1 FROM ledger.outbox WHERE event_id = %s", (event_id,)).fetchone() is None

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_binding(writer_conn, key=key, event_id=other_event)
        writer_conn.rollback()

    assert db.execute("SELECT 1 FROM ledger.events WHERE event_id = %s", (event_id,)).fetchone() is None
    assert db.execute("SELECT 1 FROM ledger.idempotency_keys WHERE key = %s", (key,)).fetchone() is None
    assert db.execute("SELECT 1 FROM ledger.outbox WHERE event_id = %s", (event_id,)).fetchone() is None
    assert db.execute("SELECT 1 FROM ledger.idempotency_bindings WHERE key = %s", (key,)).fetchone() is None
    # The key is not burned by the failure: the same claim succeeds on a later attempt.
    _claim(db, key)
