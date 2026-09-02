"""Migration 0001 — the `billing_engine` schema (task 3.1).

Covers the task's test obligation: the migration applies and reverses cleanly, the two
tables and their shapes exist, and the service role holds the grants decision 5 calls for
(upsertable, no DELETE).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"

SERVICE_ROLE = "billing_engine_service"

BILLING_ENGINE_TABLES = {"subject_facts", "evaluations"}


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "0001")


def _downgrade(database_url: str) -> None:
    command.downgrade(_alembic_config(database_url), "base")


def _billing_engine_tables(conn: psycopg.Connection) -> set[str]:
    cur = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'billing_engine'")
    return {name for (name,) in cur.fetchall()}


def _insert_fact(conn: psycopg.Connection, subject_key: str, **overrides: object) -> None:
    row: dict[str, object] = {
        "subject_type": "billing_episode",
        "subject_key": subject_key,
        "facts": psycopg.types.json.Jsonb({}),
        "last_event_id": uuid.uuid4(),
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    conn.execute(
        f"INSERT INTO billing_engine.subject_facts ({columns}) VALUES ({placeholders})",  # noqa: S608
        row,
    )


def _insert_evaluation(conn: psycopg.Connection, declared_event_id: uuid.UUID, **overrides: object) -> None:
    row: dict[str, object] = {
        "subject_type": "billing_episode",
        "subject_key": "ep-1",
        "verdict_type": "billing_eligibility",
        "rule_version": "pulse-billing_eligibility-v1",
        "outcome": "positive",
        "as_of": datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        "declared_event_id": declared_event_id,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    conn.execute(
        f"INSERT INTO billing_engine.evaluations ({columns}) VALUES ({placeholders})",  # noqa: S608
        row,
    )


def test_upgrade_creates_the_billing_engine_schema_and_downgrade_removes_it(
    database_url: str, db: psycopg.Connection
) -> None:
    _upgrade(database_url)
    assert _billing_engine_tables(db) == BILLING_ENGINE_TABLES

    _downgrade(database_url)
    cur = db.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'billing_engine'")
    assert cur.fetchone() is None
    cur = db.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (SERVICE_ROLE,))
    assert cur.fetchone() is None


def test_subject_facts_is_one_row_per_subject(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    _insert_fact(db, "ep-1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_fact(db, "ep-1")


def test_evaluations_declared_event_id_is_unique(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    declared = uuid.uuid4()
    _insert_evaluation(db, declared)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_evaluation(db, declared, subject_key="ep-2")


def test_service_role_can_upsert_but_never_delete(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    _insert_fact(db, "ep-1")
    _insert_evaluation(db, uuid.uuid4())

    db.execute(f"SET ROLE {SERVICE_ROLE}")
    db.execute(
        "UPDATE billing_engine.subject_facts SET facts = %s WHERE subject_key = 'ep-1'",
        (psycopg.types.json.Jsonb({"a": 1}),),
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM billing_engine.subject_facts WHERE subject_key = 'ep-1'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM billing_engine.evaluations")


def test_defaults_apply(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    _insert_fact(db, "ep-1")
    cur = db.execute(
        "SELECT facts, updated_at IS NOT NULL FROM billing_engine.subject_facts WHERE subject_key = 'ep-1'"
    )
    facts, updated_at_set = cur.fetchone()  # type: ignore[misc]
    assert facts == {}
    assert updated_at_set is True
