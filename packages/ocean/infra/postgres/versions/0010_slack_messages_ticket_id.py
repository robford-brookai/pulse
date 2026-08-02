"""Add ticket_id column to slack_messages for ticket thread tracking.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slack_messages", sa.Column("ticket_id", sa.Text(), nullable=True))
    op.create_index("idx_slack_messages_ticket_id", "slack_messages", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("idx_slack_messages_ticket_id", table_name="slack_messages")
    op.drop_column("slack_messages", "ticket_id")
