"""Migration 0005 — the three subject-type checks admit `communication_consent`.

Catalog release 1.1.0 seeds `communication_consent`; without this migration a catalog-legal
`record_communication_consent` command validates against the generated adjacency and is then
refused by the store — the exact gap `handoffs/pulse-demo-closeout/task-004.md` surfaced against a
real migrated Postgres. This suite asserts the widened shape itself: `communication_consent` is
accepted by `events`, `current_state`, and `review_queue`; the vocabulary 0004 admitted (the
original six grains plus `coverage`) is untouched; and the migration reverses cleanly.

It also carries the standing gate the task calls for: every subject type
`pulse_core.generated.TRANSITIONS` knows about must be admitted by all three constraints, so a
future catalog release that adds a subject type cannot reopen this gap silently — the gate goes
red at the same moment the seed does, not whenever someone next tries to commit it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from pulse_core.generated import TRANSITIONS

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

#: The vocabulary 0004 left the constraints with, which 0005 must leave untouched.
V0004_SUBJECT_TYPES = ("referral", "consent", "enrollment", "billing_episode", "device", "contract", "coverage")

CHECKED_CONSTRAINTS = {
    "events": "ck_events_subject_type",
    "current_state": "ck_current_state_subject_type",
    "review_queue": "ck_review_queue_subject_type",
}


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def _upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(_alembic_config(database_url), revision)


def _downgrade(database_url: str, revision: str) -> None:
    command.downgrade(_alembic_config(database_url), revision)


def _insert_event(conn: psycopg.Connection, subject_type: str, subject_key: str) -> uuid.UUID:
    event_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO ledger.events (event_id, subject_type, subject_key, event_type, effective_at,"
        " producer, rule_version, actor_type, actor_id)"
        " VALUES (%s, %s, %s, %s, %s, 'migration-tests', '1.1.0', 'system', 'verdict-relay')",
        (event_id, subject_type, subject_key, f"{subject_type}.test", T0),
    )
    return event_id


def _insert_current_state(conn: psycopg.Connection, subject_type: str, subject_key: str, event_id: uuid.UUID) -> None:
    conn.execute(
        "INSERT INTO ledger.current_state (subject_type, subject_key, state, effective_at, last_event_id)"
        " VALUES (%s, %s, 'unset', %s, %s)",
        (subject_type, subject_key, T0, event_id),
    )


def _insert_review_row(conn: psycopg.Connection, subject_type: str, subject_key: str, event_id: uuid.UUID) -> None:
    conn.execute(
        "INSERT INTO ledger.review_queue (subject_type, subject_key, hold_event_id) VALUES (%s, %s, %s)",
        (subject_type, subject_key, event_id),
    )


def _constraint_definitions(conn: psycopg.Connection) -> dict[str, str]:
    cur = conn.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = ANY(%s)",
        (list(CHECKED_CONSTRAINTS.values()),),
    )
    return dict(cur.fetchall())


def test_the_three_tables_admit_communication_consent(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)

    event_id = _insert_event(db, "communication_consent", "cc-1")
    _insert_current_state(db, "communication_consent", "cc-1", event_id)
    _insert_review_row(db, "communication_consent", "cc-1", event_id)

    stored = db.execute("SELECT subject_type FROM ledger.events WHERE event_id = %s", (event_id,)).fetchone()
    assert stored == ("communication_consent",)


def test_the_0004_vocabulary_is_unaffected(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    for subject_type in V0004_SUBJECT_TYPES:
        _insert_event(db, subject_type, f"{subject_type}-1")

    # A grain outside the widened set is still refused, so the constraint did not degenerate
    # into accepting anything.
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_event(db, "spaceship", "ss-1")


def test_downgrade_restores_the_0004_vocabulary(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    # Downgrade to 0004, the coverage-admitting migration — a single-step round trip.
    _downgrade(database_url, "0004")

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_event(db, "communication_consent", "cc-1")

    # The constraints exist and 0004's vocabulary still commits.
    assert set(_constraint_definitions(db)) == set(CHECKED_CONSTRAINTS.values())
    _insert_event(db, "coverage", "cov-1")


def test_all_three_constraints_carry_the_same_vocabulary(database_url: str, db: psycopg.Connection) -> None:
    """The spec widens the record as one act — a table left behind would re-open the
    validates-but-cannot-commit gap for whichever write path touches it."""
    _upgrade(database_url)
    definitions = _constraint_definitions(db)
    assert set(definitions) == set(CHECKED_CONSTRAINTS.values())
    for name, definition in definitions.items():
        assert "'communication_consent'" in definition, name
        for subject_type in V0004_SUBJECT_TYPES:
            assert f"'{subject_type}'" in definition, name


def test_every_catalog_subject_type_is_admitted_by_all_three_constraints(
    database_url: str, db: psycopg.Connection
) -> None:
    """The standing gate: whatever `pulse_core.generated.TRANSITIONS` knows about, the store must
    accept — so a future catalog release that adds a subject type cannot reopen the
    validates-but-cannot-commit gap this migration closes for `communication_consent`.
    """
    _upgrade(database_url)
    definitions = _constraint_definitions(db)
    assert set(definitions) == set(CHECKED_CONSTRAINTS.values())
    for subject_type in TRANSITIONS:
        for name, definition in definitions.items():
            assert f"'{subject_type}'" in definition, (
                f"catalog subject type {subject_type!r} is not admitted by constraint {name!r}"
            )
