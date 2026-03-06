"""connector_health table for tracking connector heartbeat state.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE connector_health (
                connector_id    TEXT PRIMARY KEY,
                connector_name  TEXT NOT NULL,
                last_seen       TIMESTAMPTZ NOT NULL,
                last_alerted_at TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE connector_health"))
