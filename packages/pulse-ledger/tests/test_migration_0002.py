"""Migration 0002 — the relay's bookkeeping columns on `ledger.outbox`.

Three things the relay depends on and the migration must actually deliver: the columns exist and
are nullable (every row 0001 already wrote has to remain valid), the claim index excludes
dead-lettered rows, and the service role can write the new columns without a further grant.
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

SERVICE_ROLE = "pulse_ledger_service"

RELAY_COLUMNS = {"next_attempt_at", "dead_lettered_at", "last_error"}


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def _columns(conn: psycopg.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns"
        " WHERE table_schema = 'ledger' AND table_name = %s",
        (table,),
    ).fetchall()
    return dict(rows)


def _seed_event(conn: psycopg.Connection) -> uuid.UUID:
    """One event plus its outbox row, by the shortest legal path."""
    event_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO ledger.events"
        " (event_id, subject_type, subject_key, event_type, effective_at, producer, rule_version,"
        "  actor_type, actor_id)"
        " VALUES (%s, 'referral', 'ref-1', 'referral.received', %s, 'test', 'state_catalog@1',"
        "         'system', 'test')",
        (event_id, datetime(2026, 7, 1, tzinfo=timezone.utc)),
    )
    conn.execute(
        "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq) VALUES (%s, 'referral', 'ref-1', 1)",
        (event_id,),
    )
    return event_id


def test_the_relay_columns_arrive_nullable(ledger_db: psycopg.Connection) -> None:
    """Nullable, so 0001's rows stay valid: an un-attempted row has no schedule and no error."""
    columns = _columns(ledger_db, "outbox")
    assert columns.keys() >= RELAY_COLUMNS
    assert all(columns[name] == "YES" for name in RELAY_COLUMNS)

    event_id = _seed_event(ledger_db)
    row = ledger_db.execute(
        "SELECT next_attempt_at, dead_lettered_at, last_error FROM ledger.outbox WHERE event_id = %s",
        (event_id,),
    ).fetchone()
    assert row == (None, None, None)


def test_the_claim_index_excludes_dead_lettered_rows(ledger_db: psycopg.Connection) -> None:
    """A poison row must leave the relay's scan, not sit in it being rescanned forever."""
    predicate = ledger_db.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'ledger' AND indexname = 'ix_outbox_unpublished'"
    ).fetchone()
    assert predicate is not None
    assert "dead_lettered_at IS NULL" in predicate[0]

    depth_index = ledger_db.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'ledger' AND indexname = 'ix_outbox_dead_lettered'"
    ).fetchone()
    assert depth_index is not None, "the monitor's depth query needs an index of its own"


def test_the_service_role_can_write_the_new_columns(ledger_db: psycopg.Connection) -> None:
    """0001's `GRANT ... UPDATE ON ledger.outbox` is table-wide, so no new grant is owed."""
    event_id = _seed_event(ledger_db)
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    try:
        ledger_db.execute(
            "UPDATE ledger.outbox SET attempts = 5, dead_lettered_at = now(), last_error = 'refused'"
            " WHERE event_id = %s",
            (event_id,),
        )
    finally:
        ledger_db.execute("RESET ROLE")

    assert ledger_db.execute("SELECT count(*) FROM ledger.outbox WHERE dead_lettered_at IS NOT NULL").fetchone() == (1,)


def test_the_migration_reverses_cleanly(database_url: str, db: psycopg.Connection) -> None:
    """Down to 0001 restores that revision's outbox exactly — columns gone, index predicate back."""
    cfg = _alembic_config(database_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")

    columns = _columns(db, "outbox")
    assert not (RELAY_COLUMNS & columns.keys())
    indexdef = db.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'ledger' AND indexname = 'ix_outbox_unpublished'"
    ).fetchone()
    assert indexdef is not None
    assert "dead_lettered_at" not in indexdef[0]

    command.upgrade(cfg, "head")
    assert _columns(db, "outbox").keys() >= RELAY_COLUMNS


def test_this_migration_is_reachable_from_a_single_head(database_url: str) -> None:
    """The sequencing hazard this guards is two heads, not a particular head.

    Pinning `head == "0002"` also fails when a later migration legitimately lands, which is
    what happened the moment 0003 arrived — a false alarm that says nothing about whether the
    sequence forked. Assert the invariant instead: one head, and this revision on the path to
    it. `tests/test_migration_graph.py` holds the same invariant for every alembic tree,
    including the duplicate-revision-id case alembic itself only warns about.
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config(database_url))
    assert len(script.get_heads()) == 1, "two heads mean a merge revision is owed"
    assert "0002" in {rev.revision for rev in script.walk_revisions()}


@pytest.mark.parametrize("column", sorted(RELAY_COLUMNS))
def test_each_relay_column_is_indexable_by_its_predicate(ledger_db: psycopg.Connection, column: str) -> None:
    """Sanity: each column exists with a type a WHERE clause can use, not just a name."""
    ledger_db.execute(f"SELECT count(*) FROM ledger.outbox WHERE {column} IS NULL")  # noqa: S608 — parametrized name
