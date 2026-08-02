"""The alembic chain applies base -> head, and every downgrade reverses.

This test is the one whose absence let 0017 sit broken. That migration wrote a
partial unique constraint inline in CREATE TABLE, which Postgres rejects, so
`alembic upgrade head` had never reached the end of the chain. Nothing here is
specific to one revision: any future migration that cannot apply, cannot be
undone, or forks the chain into two heads fails this test.

It also pins the contract tasks 3.1-3.5 write their sequence guards against:
last_event_at, nullable, TIMESTAMPTZ, no default, on the four guarded tables.

Requires Docker. The image must be pgvector/pgvector:pg16 — migration 0006
creates the vector extension, which stock postgres images do not ship.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[2] / "infra" / "postgres"

# Tables a wave-2a sequence guard protects, and the column each guard compares.
GUARDED_TABLES = ("interactions", "device_associations", "signals", "slack_messages")
GUARD_COLUMN = "last_event_at"


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def migration_db():
    """A Postgres container with pgvector, plus a sync URL for the alembic runner."""
    if not _docker_available():
        pytest.skip("Docker not available — skipping migration chain test")
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed")

    # Migration 0006 runs CREATE EXTENSION vector; only the pgvector image has it.
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url()
        # env.py strips +asyncpg; normalise whatever driver testcontainers named.
        yield url.replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="module")
def alembic_config(migration_db):
    """Alembic config pointed at the container.

    infra/postgres/env.py reads DATABASE_URL from the environment rather than
    from the Config object, so the variable is set for the fixture's lifetime.
    """
    from alembic.config import Config

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = migration_db

    config = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    yield config

    if previous is None:
        del os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="module")
def applied_head(alembic_config, migration_db):
    """Run the whole chain to head once, and yield an engine over the result."""
    from alembic import command

    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(migration_db)
    yield engine
    engine.dispose()


# --- The chain --------------------------------------------------------------


def test_exactly_one_head(alembic_config):
    """Two heads mean two migrations claimed the same predecessor.

    That is what parallel worktrees produce when each writes its own next
    migration — the failure task 3.0 exists to prevent for wave 2a.
    """
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(alembic_config).get_heads()
    assert len(heads) == 1, f"Expected a single alembic head, found: {sorted(heads)}"


def test_chain_applies_from_base_to_head(applied_head):
    """Every migration, in order, against a real Postgres."""
    with applied_head.connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0019"


def test_chain_downgrades_back_to_base(alembic_config, applied_head, migration_db):
    """Every downgrade reverses its upgrade, leaving no tables behind."""
    from alembic import command

    command.downgrade(alembic_config, "base")

    with sa.create_engine(migration_db).connect() as conn:
        remaining = sorted(
            row[0] for row in conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        )
    # alembic_version is alembic's own bookkeeping and survives a downgrade to base.
    assert remaining == ["alembic_version"], f"Downgrade left tables behind: {remaining}"

    # Leave the database at head for any test ordered after this one.
    command.upgrade(alembic_config, "head")


# --- The wave-2a guard contract ---------------------------------------------


@pytest.mark.parametrize("table", GUARDED_TABLES)
def test_guard_column_present_and_nullable(applied_head, table):
    with applied_head.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT is_nullable, data_type, column_default FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": GUARD_COLUMN},
        ).one_or_none()

    assert row is not None, f"{table}.{GUARD_COLUMN} is missing — a wave-2a guard reads it there"
    is_nullable, data_type, column_default = row
    assert is_nullable == "YES", "A pre-migration row has no known event time and must read as overwritable"
    assert data_type == "timestamp with time zone"
    assert column_default is None, "A default would record processing time, which is the defect wave 2a removes"


def test_append_only_outcomes_has_no_guard_column(applied_head):
    """outcomes is ON CONFLICT (outcome_id) DO NOTHING — nothing to overwrite, nothing to guard."""
    with applied_head.connect() as conn:
        found = conn.execute(
            sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = 'outcomes' AND column_name = :column"),
            {"column": GUARD_COLUMN},
        ).one_or_none()
    assert found is None


def test_guard_column_is_not_indexed(applied_head):
    """Every guard reads the column on a row already located by an existing key.

    interactions and signals by primary key, device_associations by its
    UNIQUE (patient_id, device_id), slack_messages by task_id or message_ts. An
    index on last_event_at would be written by every projection and read by none.
    """
    with applied_head.connect() as conn:
        indexed = (
            conn
            .execute(
                sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexdef LIKE :pattern"),
                {"pattern": f"%({GUARD_COLUMN})%"},
            )
            .scalars()
            .all()
        )
    assert indexed == [], f"Unexpected index on {GUARD_COLUMN}: {indexed}"
