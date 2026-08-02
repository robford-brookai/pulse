"""ai_drafts table for tracking AI-generated outreach drafts and approval state.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE ai_drafts (
                draft_id    TEXT PRIMARY KEY,
                task_id     TEXT NOT NULL REFERENCES tasks(task_id),
                patient_id  TEXT NOT NULL,
                alert_id    TEXT NOT NULL,
                draft_text  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                actor_id    TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_ai_drafts_task_id ON ai_drafts(task_id)"))
    op.execute(sa.text("CREATE INDEX ix_ai_drafts_status ON ai_drafts(status)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE ai_drafts"))
