"""Drop patients.enrollment_status's default and add ledger_seq (patient-state projection).

`enrollment_status` has been minted by the alerts handler's bootstrap insert with a
hardcoded `'pending'`, both as the column's `server_default` and as `models.py`'s
`default="pending"`. The patient-state projection (design.md decision 2) mints the row
itself from the ledger's first `enrollment` event and always supplies a status, so the
default is now a trap: any writer that forgets to set it gets a value the ledger never
asserted. `ledger_seq BIGINT NULL` is the citation — set for every row the projection
writes, null for a legacy row the bootstrap insert minted before this change (design.md
decision 3, 5). NOT NULL stays on `enrollment_status` itself: every projected write
supplies a value and every legacy row already has one.

`patient_graph_summary` is a materialized view and cannot be altered in place, so it is
dropped and recreated with `ledger_seq` carried through the select and group-by, and its
unique index recreated identically (design.md decision 7).

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Materialized views cannot be altered; drop before the column change it depends on.
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS patient_graph_summary"))

    op.alter_column("patients", "enrollment_status", server_default=None)
    op.add_column("patients", sa.Column("ledger_seq", sa.BigInteger(), nullable=True))

    op.execute(
        sa.text(
            """
            CREATE MATERIALIZED VIEW patient_graph_summary AS
            SELECT
                p.patient_id,
                p.enrollment_status,
                p.ledger_seq,
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
            GROUP BY p.patient_id, p.enrollment_status, p.ledger_seq
            """
        )
    )
    op.execute(sa.text("CREATE UNIQUE INDEX idx_patient_graph_summary_pk ON patient_graph_summary (patient_id)"))


def downgrade() -> None:
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS patient_graph_summary"))

    op.drop_column("patients", "ledger_seq")
    op.alter_column("patients", "enrollment_status", server_default="pending")

    op.execute(
        sa.text(
            """
            CREATE MATERIALIZED VIEW patient_graph_summary AS
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
    op.execute(sa.text("CREATE UNIQUE INDEX idx_patient_graph_summary_pk ON patient_graph_summary (patient_id)"))
