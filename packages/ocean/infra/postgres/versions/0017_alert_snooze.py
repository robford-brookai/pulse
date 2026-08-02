"""Add alert_snoozes table for snooze-based alert suppression.

Care team can snooze an alert from Slack for a configurable duration,
suppressing re-routing until expiry. The control-plane routing guard
checks this table before creating a new task for a snoozed alert.

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE TABLE alert_snoozes ("
            "  id SERIAL PRIMARY KEY,"
            "  alert_id TEXT NOT NULL,"
            "  snoozed_by TEXT NOT NULL,"
            "  snoozed_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  snooze_until TIMESTAMPTZ NOT NULL,"
            "  reason TEXT,"
            "  active BOOLEAN DEFAULT true"
            ")"
        )
    )
    # One live snooze per alert. A partial constraint has no inline CREATE TABLE
    # form in Postgres — it is only ever a separate CREATE UNIQUE INDEX.
    op.execute(
        sa.text("CREATE UNIQUE INDEX alert_snoozes_alert_id_active_key ON alert_snoozes (alert_id) WHERE active")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS alert_snoozes"))
