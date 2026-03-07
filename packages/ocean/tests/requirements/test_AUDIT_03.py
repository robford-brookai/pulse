"""AUDIT-03: Audit log retention supports 6-year lookback via monthly partitioning.

Verifies migration 0007 correctly converts audit_log to a partitioned table
with monthly partitions and a DEFAULT partition. Tests immutability trigger
propagation to partitions (PG16 auto-inheritance).

Requires Docker (testcontainers Postgres).
Uses asyncpg directly (no SQLAlchemy overhead, no greenlet dependency).
"""
from __future__ import annotations

import asyncio
import datetime
import uuid
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# DDL constants
# ---------------------------------------------------------------------------

_IMMUTABLE_FUNC_DDL = """
CREATE OR REPLACE FUNCTION audit_log_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: UPDATE and DELETE are not permitted (HIPAA 45 C.F.R. %% 164.312(b))';
END;
$$;
"""

_ORIGINAL_TABLE_DDL = """
CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY,
    event_id UUID,
    action_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
"""


def _docker_available() -> bool:
    import subprocess

    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _docker_available(), reason="Docker not available"),
    pytest.mark.integration,
]


def _build_dsn(url: str) -> dict:
    """Parse testcontainers URL into asyncpg connect kwargs."""
    parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://"))
    return {
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/"),
    }


def _run_migration(dsn: dict) -> None:
    """Run migration 0007 DDL synchronously (via asyncio.run) against the test DB."""

    async def _migrate():
        conn = await asyncpg.connect(**dsn)
        try:
            # 1. Create immutability function (from migration 0001)
            await conn.execute(_IMMUTABLE_FUNC_DDL)

            # 2. Create original non-partitioned audit_log (simulates pre-0007 state)
            await conn.execute(_ORIGINAL_TABLE_DDL)

            # 3. Run the 0007 upgrade logic
            await conn.execute("ALTER TABLE audit_log RENAME TO audit_log_legacy;")
            await conn.execute(
                "DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log_legacy;"
            )

            await conn.execute("""
                CREATE TABLE audit_log (
                    audit_id UUID NOT NULL,
                    event_id UUID,
                    action_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,
                    timestamp TIMESTAMPTZ NOT NULL,
                    detail JSONB NOT NULL DEFAULT '{}',
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (audit_id, recorded_at)
                ) PARTITION BY RANGE (recorded_at);
            """)

            today = datetime.date.today()
            for offset in range(-1, 13):
                total_months = (today.year * 12 + today.month - 1) + offset
                year = total_months // 12
                month = total_months % 12 + 1
                next_total = total_months + 1
                next_year = next_total // 12
                next_month = next_total % 12 + 1
                name = f"audit_log_y{year}m{month:02d}"
                start = f"{year}-{month:02d}-01"
                end = f"{next_year}-{next_month:02d}-01"
                await conn.execute(
                    f"CREATE TABLE {name} PARTITION OF audit_log "
                    f"FOR VALUES FROM ('{start}') TO ('{end}');"
                )

            await conn.execute("CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;")

            await conn.execute("CREATE INDEX ix_audit_log_timestamp ON audit_log (timestamp);")
            await conn.execute("CREATE INDEX ix_audit_log_actor ON audit_log (actor_id);")
            await conn.execute(
                "CREATE INDEX ix_audit_log_entity ON audit_log (entity_type, entity_id);"
            )
            await conn.execute("CREATE INDEX ix_audit_log_event_id ON audit_log (event_id);")

            await conn.execute("""
                CREATE TRIGGER audit_log_no_update_delete
                BEFORE UPDATE OR DELETE ON audit_log
                FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
            """)

            await conn.execute("INSERT INTO audit_log SELECT * FROM audit_log_legacy;")
            await conn.execute("DROP TABLE audit_log_legacy;")
        finally:
            await conn.close()

    asyncio.run(_migrate())


@pytest.fixture(scope="module")
def pg_dsn():
    """Module-scoped Postgres 16 container with migration applied. Returns DSN dict."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed")

    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = _build_dsn(pg.get_connection_url())
        _run_migration(dsn)
        yield dsn


@pytest_asyncio.fixture
async def conn(pg_dsn):
    """Per-test asyncpg connection (function-scoped, fresh event loop each test)."""
    connection = await asyncpg.connect(**pg_dsn)
    yield connection
    await connection.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_partitioned(conn):
    """audit_log must be a partitioned table (relkind='p' in pg_class)."""
    row = await conn.fetchrow(
        "SELECT relkind FROM pg_class WHERE relname = 'audit_log'"
    )
    assert row is not None, "audit_log not found in pg_class"
    relkind = row["relkind"]
    # asyncpg returns pg "char" type as bytes
    if isinstance(relkind, bytes):
        relkind = relkind.decode()
    assert relkind == "p", f"Expected relkind='p' (partitioned), got '{relkind}'"


@pytest.mark.asyncio
async def test_at_least_12_monthly_partitions(conn):
    """At least 12 monthly child partitions must exist."""
    count = await conn.fetchval("""
        SELECT COUNT(*)
        FROM pg_inherits
        WHERE inhparent = (SELECT oid FROM pg_class WHERE relname = 'audit_log')
    """)
    # 14 monthly + 1 default = 15
    assert count >= 13, f"Expected >= 13 child partitions (12 monthly + default), got {count}"


@pytest.mark.asyncio
async def test_default_partition_exists(conn):
    """A DEFAULT partition named audit_log_default must exist."""
    row = await conn.fetchrow(
        "SELECT relname FROM pg_class WHERE relname = 'audit_log_default'"
    )
    assert row is not None, "audit_log_default partition not found"


@pytest.mark.asyncio
async def test_immutability_trigger_on_partitioned_table(conn):
    """INSERT then UPDATE must raise due to immutability trigger."""
    audit_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.timezone.utc)

    await conn.execute("""
        INSERT INTO audit_log (audit_id, action_type, actor_id, source_system, timestamp, recorded_at)
        VALUES ($1, 'test.insert', 'test-actor', 'test-system', $2, $2)
    """, audit_id, now)

    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await conn.execute("""
            UPDATE audit_log SET action_type = 'tampered' WHERE audit_id = $1
        """, audit_id)


@pytest.mark.asyncio
async def test_data_lands_in_correct_partition(conn):
    """An INSERT with a known recorded_at should land in the matching monthly partition."""
    today = datetime.date.today()
    partition_name = f"audit_log_y{today.year}m{today.month:02d}"
    audit_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.timezone.utc)

    await conn.execute("""
        INSERT INTO audit_log (audit_id, action_type, actor_id, source_system, timestamp, recorded_at)
        VALUES ($1, 'test.partition', 'test-actor', 'test-system', $2, $2)
    """, audit_id, now)

    # Query the specific partition directly
    row = await conn.fetchrow(
        f"SELECT audit_id FROM {partition_name} WHERE audit_id = $1",
        audit_id,
    )
    assert row is not None, f"Row not found in partition {partition_name}"
