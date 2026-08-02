"""Convert audit_log to monthly-partitioned table for 6-year HIPAA retention.

Implements AUDIT-03: native Postgres declarative partitioning on audit_log
by recorded_at column. Creates 14 monthly partitions (1 back + 12 forward)
plus a DEFAULT partition. Re-creates indexes and immutability trigger on the
partitioned parent (PG16 auto-inherits to partitions).

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-07
"""

from __future__ import annotations

import datetime

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _partition_boundaries() -> list[tuple[str, str, str]]:
    """Return (partition_name, start_date, end_date) for 14 monthly partitions.

    Range: 1 month back through 12 months forward from today.
    """
    today = datetime.date.today()
    partitions: list[tuple[str, str, str]] = []

    for offset in range(-1, 13):
        # Calculate year/month with offset
        total_months = (today.year * 12 + today.month - 1) + offset
        year = total_months // 12
        month = total_months % 12 + 1

        # Next month boundary
        next_total = total_months + 1
        next_year = next_total // 12
        next_month = next_total % 12 + 1

        name = f"audit_log_y{year}m{month:02d}"
        start = f"{year}-{month:02d}-01"
        end = f"{next_year}-{next_month:02d}-01"
        partitions.append((name, start, end))

    return partitions


def upgrade() -> None:
    # 1. Rename existing table to legacy
    op.rename_table("audit_log", "audit_log_legacy")

    # 2. Drop trigger on legacy table (allows data migration via UPDATE/DELETE if needed)
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log_legacy;")

    # 3. Create new partitioned audit_log with identical columns
    #    PK includes recorded_at because partition key must be in PK.
    op.execute("""
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

    # 4. Create monthly partitions: 1 month back through 12 months forward
    for name, start, end in _partition_boundaries():
        op.execute(f"CREATE TABLE {name} PARTITION OF audit_log FOR VALUES FROM ('{start}') TO ('{end}');")

    # 5. Create DEFAULT partition for rows outside defined ranges
    op.execute("CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;")

    # 6. Drop legacy indexes (rename_table keeps old index names on audit_log_legacy)
    op.execute("DROP INDEX IF EXISTS ix_audit_log_timestamp;")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_actor;")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_entity;")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_event_id;")

    # 7. Re-create indexes on parent (auto-inherited by partitions)
    op.execute("CREATE INDEX ix_audit_log_timestamp ON audit_log (timestamp);")
    op.execute("CREATE INDEX ix_audit_log_actor ON audit_log (actor_id);")
    op.execute("CREATE INDEX ix_audit_log_entity ON audit_log (entity_type, entity_id);")
    op.execute("CREATE INDEX ix_audit_log_event_id ON audit_log (event_id);")

    # 7. Re-create immutability trigger on parent
    #    audit_log_immutable() function already exists from migration 0001
    op.execute("""
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
    """)

    # 8. Migrate data from legacy table
    op.execute("INSERT INTO audit_log SELECT * FROM audit_log_legacy;")

    # 9. Drop legacy table
    op.execute("DROP TABLE audit_log_legacy;")


def downgrade() -> None:
    # 1. Create non-partitioned legacy table with original schema
    op.execute("""
        CREATE TABLE audit_log_legacy (
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
    """)

    # 2. Migrate data from partitioned table
    op.execute("INSERT INTO audit_log_legacy SELECT * FROM audit_log;")

    # 3. Drop partitioned table (CASCADE drops partitions, indexes, triggers)
    op.execute("DROP TABLE audit_log CASCADE;")

    # 4. Rename legacy back to audit_log
    op.rename_table("audit_log_legacy", "audit_log")

    # 5. Re-create indexes on the non-partitioned table
    op.execute("CREATE INDEX ix_audit_log_timestamp ON audit_log (timestamp);")
    op.execute("CREATE INDEX ix_audit_log_actor ON audit_log (actor_id);")
    op.execute("CREATE INDEX ix_audit_log_entity ON audit_log (entity_type, entity_id);")
    op.execute("CREATE INDEX ix_audit_log_event_id ON audit_log (event_id);")

    # 6. Re-create immutability trigger
    op.execute("""
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
    """)
