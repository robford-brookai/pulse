"""Migration 0004 — the three subject-type checks admit `coverage`.

Catalog release 1.1.0 added the `coverage` subject; without this migration a catalog-legal
coverage transition validates and is then refused by the store — the exact gap
`test_communication_consent_validates_but_cannot_yet_be_committed` pins for the subject that
remains outside the record. This suite asserts the widened shape itself: `coverage` is accepted
by `events`, `current_state`, and `review_queue`; the six original grains are untouched;
`communication_consent` is still refused (it is `ownership: recorded`, not admitted by this
change); and the migration reverses cleanly.
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

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

#: The six grains migration 0001 admitted, which 0004 must leave untouched.
ORIGINAL_SUBJECT_TYPES = ("referral", "consent", "enrollment", "billing_episode", "device", "contract")

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
        " VALUES (%s, %s, 'unverified', %s, %s)",
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


def test_the_three_tables_admit_coverage(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)

    event_id = _insert_event(db, "coverage", "cov-1")
    _insert_current_state(db, "coverage", "cov-1", event_id)
    _insert_review_row(db, "coverage", "cov-1", event_id)

    stored = db.execute("SELECT subject_type FROM ledger.events WHERE event_id = %s", (event_id,)).fetchone()
    assert stored == ("coverage",)


def test_the_original_six_grains_are_unaffected(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    for subject_type in ORIGINAL_SUBJECT_TYPES:
        _insert_event(db, subject_type, f"{subject_type}-1")

    # And a grain outside the widened set is still refused, so the constraints did not
    # degenerate into accepting anything.
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_event(db, "spaceship", "ss-1")


def test_communication_consent_is_still_outside_the_record(database_url: str, db: psycopg.Connection) -> None:
    """0004 admits `coverage` only; the recorded-ownership subject stays pinned out (see
    `test_communication_consent_validates_but_cannot_yet_be_committed`)."""
    _upgrade(database_url)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_event(db, "communication_consent", "cc-1")


def test_downgrade_restores_the_six_grain_constraints(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    # Downgrade to 0003, the identity-registry migration — a single-step round trip.
    _downgrade(database_url, "0003")

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_event(db, "coverage", "cov-1")

    # The constraints exist and the tables the earlier migrations own are untouched.
    assert set(_constraint_definitions(db)) == set(CHECKED_CONSTRAINTS.values())
    _insert_event(db, "referral", "ref-1")


def test_all_three_constraints_carry_the_same_vocabulary(database_url: str, db: psycopg.Connection) -> None:
    """The spec widens the record as one act — a table left behind would re-open the
    validates-but-cannot-commit gap for whichever write path touches it."""
    _upgrade(database_url)
    definitions = _constraint_definitions(db)
    assert set(definitions) == set(CHECKED_CONSTRAINTS.values())
    for name, definition in definitions.items():
        assert "'coverage'" in definition, name
        for subject_type in ORIGINAL_SUBJECT_TYPES:
            assert f"'{subject_type}'" in definition, name
        assert "communication_consent" not in definition, name
