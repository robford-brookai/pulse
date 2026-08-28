"""Migration 0003 — the identity registry's shape, and the queue's drain constraint.

What the store must guarantee regardless of which caller writes: `(system, value)` resolves to at
most one person, a match key is a digest and never readable demographics, a resolved review names
the resolution that drained it, and a subject is pending at most once. The behaviour those shapes
support is asserted in `test_identity.py` and `test_review.py`; this suite asserts the shapes
themselves, and that the migration reverses cleanly.
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

ADDED_TABLES = {"external_identifiers", "person_match_keys"}

#: A well-formed digest with a letter in it, so the uppercase case below is genuinely different.
DIGEST = "a" * 64

PERSON_A = "tide-000000000000000a"
PERSON_B = "tide-000000000000000b"


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(_alembic_config(database_url), revision)


def _downgrade(database_url: str, revision: str) -> None:
    command.downgrade(_alembic_config(database_url), revision)


def _ledger_tables(conn: psycopg.Connection) -> set[str]:
    cur = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'ledger'")
    return {name for (name,) in cur.fetchall()}


def _hold_event(conn: psycopg.Connection, subject_key: str = "ref-1") -> uuid.UUID:
    event_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO ledger.events (event_id, subject_type, subject_key, event_type, effective_at,"
        " producer, rule_version, actor_type, actor_id)"
        " VALUES (%s, 'referral', %s, 'resolution_hold', %s, 'identity-resolver', 'appendix-c-v0.7',"
        " 'system', 'identity-resolver')",
        (event_id, subject_key, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)),
    )
    return event_id


def _queue_row(conn: psycopg.Connection, subject_key: str = "ref-1", **overrides: Any) -> uuid.UUID:
    row: dict[str, Any] = {
        "subject_type": "referral",
        "subject_key": subject_key,
        "hold_event_id": _hold_event(conn, subject_key),
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    cur = conn.execute(
        f"INSERT INTO ledger.review_queue ({columns}) VALUES ({placeholders}) RETURNING review_id",  # noqa: S608
        row,
    )
    return cur.fetchone()[0]  # type: ignore[index]


def test_upgrade_adds_the_registry_and_downgrade_removes_it(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    assert _ledger_tables(db) >= ADDED_TABLES
    assert _review_queue_columns(db) >= {"resolution_event_id"}

    # Downgrade to 0002, not 0001: 0002 is the outbox relay migration, and stepping past it
    # would make this a round trip over two migrations instead of this one.
    _downgrade(database_url, "0002")
    assert not ADDED_TABLES & _ledger_tables(db)
    assert "resolution_event_id" not in _review_queue_columns(db)
    # The tables the earlier migrations own are untouched by the round trip.
    assert {"events", "current_state", "review_queue"} <= _ledger_tables(db)


def _review_queue_columns(conn: psycopg.Connection) -> set[str]:
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = 'ledger' AND table_name = 'review_queue'"
    )
    return {name for (name,) in cur.fetchall()}


def test_an_identifier_resolves_to_at_most_one_person(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    db.execute(
        "INSERT INTO ledger.external_identifiers (system, value, person_key, actor_type, actor_id)"
        " VALUES ('urn:test', 'MRN-001', %s, 'system', 'resolver')",
        (PERSON_A,),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO ledger.external_identifiers (system, value, person_key, actor_type, actor_id)"
            " VALUES ('urn:test', 'MRN-001', %s, 'system', 'resolver')",
            (PERSON_B,),
        )


def test_identifier_fields_must_carry_something(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    for system, value, person_key in (("  ", "MRN-001", PERSON_A), ("urn:test", "", PERSON_A), ("urn:test", "M", " ")):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO ledger.external_identifiers (system, value, person_key, actor_type, actor_id)"
                " VALUES (%s, %s, %s, 'system', 'resolver')",
                (system, value, person_key),
            )


def test_a_match_key_must_be_a_digest(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    db.execute("INSERT INTO ledger.person_match_keys (person_key, match_key) VALUES (%s, %s)", (PERSON_A, DIGEST))

    for bad in ("doe|1970-01-01|f|j", DIGEST.upper(), DIGEST[:-1], DIGEST + "0"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO ledger.person_match_keys (person_key, match_key) VALUES (%s, %s)",
                (PERSON_B, bad),
            )


def test_a_resolved_review_must_name_its_resolution(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    review_id = _queue_row(db)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE ledger.review_queue SET pending = false WHERE review_id = %s", (review_id,))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "UPDATE ledger.review_queue SET pending = false, resolved_at = now() WHERE review_id = %s",
            (review_id,),
        )


def test_a_resolution_must_reference_a_committed_event(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    review_id = _queue_row(db)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "UPDATE ledger.review_queue SET pending = false, resolved_at = now(),"
            " resolution_event_id = %s WHERE review_id = %s",
            (uuid.uuid4(), review_id),
        )


def test_only_one_pending_review_per_subject(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    first = _queue_row(db)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _queue_row(db)

    # Resolving the first frees the subject for a later quarantine.
    resolution = _hold_event(db, "ref-1")
    db.execute(
        "UPDATE ledger.review_queue SET pending = false, resolved_at = now(), resolution_event_id = %s"
        " WHERE review_id = %s",
        (resolution, first),
    )
    assert _queue_row(db) != first


def test_the_service_role_may_resolve_identifiers_but_not_move_them(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    db.execute(f"SET ROLE {SERVICE_ROLE}")
    try:
        db.execute(
            "INSERT INTO ledger.external_identifiers (system, value, person_key, actor_type, actor_id)"
            " VALUES ('urn:test', 'MRN-001', %s, 'system', 'resolver')",
            (PERSON_A,),
        )
        db.execute("INSERT INTO ledger.person_match_keys (person_key, match_key) VALUES (%s, %s)", (PERSON_A, DIGEST))
        for statement in (
            "UPDATE ledger.external_identifiers SET person_key = 'other'",
            "DELETE FROM ledger.external_identifiers",
            "UPDATE ledger.person_match_keys SET match_key = 'x'",
            "DELETE FROM ledger.person_match_keys",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
    finally:
        db.execute("RESET ROLE")
