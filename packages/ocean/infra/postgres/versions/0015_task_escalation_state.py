"""Add task_escalation_state table for escalation policy tracking.

Also makes outcomes.interaction_id nullable to support task/ticket/alert
outcomes that have no interaction.

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE task_escalation_state (
                id                  SERIAL PRIMARY KEY,
                entity_type         TEXT NOT NULL,
                entity_id           TEXT NOT NULL,
                priority_at_creation TEXT NOT NULL,
                current_priority    TEXT NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL,
                last_checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                escalated_at        TIMESTAMPTZ,
                escalation_count    INTEGER NOT NULL DEFAULT 0,
                UNIQUE (entity_type, entity_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX ix_escalation_state_unclaimed
                ON task_escalation_state(entity_type, current_priority, created_at)
                WHERE escalated_at IS NULL OR escalation_count < 3
            """
        )
    )
    # Make interaction_id nullable for task/ticket/alert outcomes
    op.execute(sa.text("ALTER TABLE outcomes ALTER COLUMN interaction_id DROP NOT NULL"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE outcomes ALTER COLUMN interaction_id SET NOT NULL"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_escalation_state_unclaimed"))
    op.execute(sa.text("DROP TABLE IF EXISTS task_escalation_state"))
