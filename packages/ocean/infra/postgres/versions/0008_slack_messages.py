"""slack_messages table for tracking Slack thread persistence.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE slack_messages (
                id          SERIAL PRIMARY KEY,
                task_id     TEXT NOT NULL,
                channel     TEXT NOT NULL,
                message_ts  TEXT NOT NULL,
                thread_ts   TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'open',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX idx_slack_messages_task_id ON slack_messages(task_id)"))
    op.execute(sa.text("CREATE UNIQUE INDEX idx_slack_messages_ts ON slack_messages(message_ts)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE slack_messages"))
