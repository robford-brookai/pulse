"""Migration 0001 — the `ledger` schema.

Covers the task's three test obligations: the migration applies and reverses cleanly,
the UPDATE/DELETE revoke on `events` holds for the service role, and the co-commit
constraint shape (current_state FK + one-row-per-subject, outbox per-subject seq,
server-set recorded_at, evidence/epoch defaults, E3 bounds, reversal FK).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"

SERVICE_ROLE = "pulse_ledger_service"

LEDGER_TABLES = {
    "events",
    "current_state",
    "idempotency_keys",
    "outbox",
    "writer_state",
    "review_queue",
}


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade(database_url: str) -> None:
    # Pinned to `0001`, not `head`: this suite asserts the shape of the schema *this* migration
    # creates, so a later revision adding a table must not make it fail.
    command.upgrade(_alembic_config(database_url), "0001")


def _downgrade(database_url: str) -> None:
    command.downgrade(_alembic_config(database_url), "base")


def _insert_event(conn: psycopg.Connection, event_id: uuid.UUID, **overrides: Any) -> None:
    row: dict[str, Any] = {
        "event_id": event_id,
        "subject_type": "referral",
        "subject_key": "ref-1",
        "event_type": "referral.received",
        "effective_at": datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        "producer": "test-writer",
        "rule_version": "state_catalog@1",
        "actor_type": "system",
        "actor_id": "test-writer",
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    conn.execute(f"INSERT INTO ledger.events ({columns}) VALUES ({placeholders})", row)  # noqa: S608


def _ledger_tables(conn: psycopg.Connection) -> set[str]:
    cur = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'ledger'")
    return {name for (name,) in cur.fetchall()}


def test_upgrade_creates_the_ledger_schema_and_downgrade_removes_it(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    assert _ledger_tables(db) == LEDGER_TABLES

    _downgrade(database_url)
    cur = db.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'ledger'")
    assert cur.fetchone() is None
    cur = db.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (SERVICE_ROLE,))
    assert cur.fetchone() is None


def test_service_role_cannot_update_or_delete_events(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    committed = uuid.uuid4()
    _insert_event(db, committed)

    db.execute(f"SET ROLE {SERVICE_ROLE}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE ledger.events SET subject_key = 'tampered' WHERE event_id = %s", (committed,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM ledger.events WHERE event_id = %s", (committed,))

    # The role's write path stays open: append and read are granted.
    _insert_event(db, uuid.uuid4(), subject_key="ref-2")
    cur = db.execute("SELECT subject_key FROM ledger.events WHERE event_id = %s", (committed,))
    assert cur.fetchone() == ("ref-1",)


def test_current_state_requires_a_committed_event(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "INSERT INTO ledger.current_state (subject_type, subject_key, state, effective_at, last_event_id)"
            " VALUES ('referral', 'ref-1', 'received', now(), %s)",
            (uuid.uuid4(),),
        )


def test_one_current_state_row_per_subject(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    event_id = uuid.uuid4()
    _insert_event(db, event_id)
    db.execute(
        "INSERT INTO ledger.current_state (subject_type, subject_key, state, effective_at, last_event_id)"
        " VALUES ('referral', 'ref-1', 'received', now(), %s)",
        (event_id,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO ledger.current_state (subject_type, subject_key, state, effective_at, last_event_id)"
            " VALUES ('referral', 'ref-1', 'resolved', now(), %s)",
            (event_id,),
        )


def test_outbox_per_subject_seq_is_unique(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    first, second = uuid.uuid4(), uuid.uuid4()
    _insert_event(db, first)
    _insert_event(db, second)
    db.execute(
        "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq) VALUES (%s, 'referral', 'ref-1', 1)",
        (first,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq) VALUES (%s, 'referral', 'ref-1', 1)",
            (second,),
        )
    # A different subject reuses the same seq freely — the sequence is per subject.
    db.execute(
        "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq) VALUES (%s, 'referral', 'ref-2', 1)",
        (second,),
    )


def test_recorded_at_is_server_set_and_defaults_apply(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    event_id = uuid.uuid4()
    _insert_event(db, event_id)
    cur = db.execute(
        "SELECT recorded_at IS NOT NULL, evidence_class, epoch, schema_version, payload"
        " FROM ledger.events WHERE event_id = %s",
        (event_id,),
    )
    recorded_at_set, evidence_class, epoch, schema_version, payload = cur.fetchone()  # type: ignore[misc]
    assert recorded_at_set is True
    assert evidence_class == "E0"
    assert epoch == "declared"
    assert schema_version == 1
    assert payload == {}


def test_e3_events_must_carry_interval_bounds(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_event(db, uuid.uuid4(), evidence_class="E3", epoch="reconstructed")
    _insert_event(
        db,
        uuid.uuid4(),
        evidence_class="E3",
        epoch="reconstructed",
        evidence_bound_lower=datetime(2026, 1, 1, tzinfo=timezone.utc),
        evidence_bound_upper=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )


def test_reversal_must_reference_a_committed_event(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_event(db, uuid.uuid4(), reverses_event_id=uuid.uuid4())

    voided = uuid.uuid4()
    reversal = uuid.uuid4()
    _insert_event(db, voided)
    _insert_event(db, reversal, event_type="referral.received.reversed", reverses_event_id=voided)
    cur = db.execute(
        "SELECT count(*) FROM ledger.events WHERE event_id = ANY(%s)",
        ([voided, reversal],),
    )
    assert cur.fetchone() == (2,)
