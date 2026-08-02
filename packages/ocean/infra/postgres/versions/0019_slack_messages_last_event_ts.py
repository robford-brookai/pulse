"""Add last_event_ts sequence column to slack_messages.

The column holds the event time of the newest event already applied to a
stored Slack message. Consumers compare against it before issuing chat.update,
so a late-arriving older event is dropped rather than overwriting newer text.
It is event time, never processing time: updated_at already carries the latter
and must not be used for ordering.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slack_messages", sa.Column("last_event_ts", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("slack_messages", "last_event_ts")
