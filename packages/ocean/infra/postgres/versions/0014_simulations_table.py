"""Simulations table for projected scenario.completed events.

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE simulations (
                scenario_name    TEXT PRIMARY KEY,
                completed_at     TIMESTAMPTZ NOT NULL,
                patients_count   INTEGER NOT NULL DEFAULT 0,
                alerts_generated INTEGER NOT NULL DEFAULT 0,
                tasks_created    INTEGER NOT NULL DEFAULT 0,
                duration_seconds FLOAT NOT NULL DEFAULT 0.0,
                last_event_id    TEXT
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_simulations_completed_at ON simulations(completed_at DESC)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE simulations"))
