"""pgvector extension, embedding columns, ivfflat indexes, and patient_graph_summary view.

Adds semantic search infrastructure for the stacte-bridge service.
Requires pgvector extension (available in pgvector/pgvector:pg16 image).

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension (requires pgvector/pgvector:pg16 image)
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # Add embedding columns (voyage-3 = 1024 dims)
    for table in ("alerts", "tasks", "interactions", "outcomes"):
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS embedding vector(1024)"))

    # IVFFlat indexes for cosine similarity search
    # lists=100 is appropriate for ~10K entities; adjust for larger datasets
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_alerts_embed "
            "ON alerts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_tasks_embed "
            "ON tasks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_interactions_embed "
            "ON interactions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_outcomes_embed "
            "ON outcomes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
    )

    # Materialized view: graph summary per patient for stacte-bridge /patient/{id}/summary
    op.execute(
        sa.text(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS patient_graph_summary AS
            SELECT
                p.patient_id,
                p.enrollment_status,
                COUNT(DISTINCT a.alert_id)       AS alert_count,
                COUNT(DISTINCT t.task_id)         AS task_count,
                COUNT(DISTINCT i.interaction_id)  AS interaction_count,
                COUNT(DISTINCT o.outcome_id)      AS outcome_count,
                MAX(a.created_at)                 AS last_alert_at,
                MAX(i.started_at)                 AS last_call_at,
                ARRAY_AGG(DISTINCT a.alert_type) FILTER (WHERE a.alert_type IS NOT NULL)
                    AS alert_types,
                ARRAY_AGG(DISTINCT o.outcome_type) FILTER (WHERE o.outcome_type IS NOT NULL)
                    AS outcome_types
            FROM patients p
            LEFT JOIN alerts       a ON a.patient_id = p.patient_id
            LEFT JOIN tasks        t ON t.patient_id = p.patient_id
            LEFT JOIN interactions i ON i.patient_id = p.patient_id
            LEFT JOIN outcomes     o ON o.patient_id = p.patient_id
            GROUP BY p.patient_id, p.enrollment_status
            """
        )
    )
    op.execute(
        sa.text("CREATE UNIQUE INDEX IF NOT EXISTS idx_patient_graph_summary_pk ON patient_graph_summary (patient_id)")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS patient_graph_summary"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_outcomes_embed"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_interactions_embed"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_tasks_embed"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_alerts_embed"))

    for table in ("alerts", "tasks", "interactions", "outcomes"):
        op.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding"))

    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))
