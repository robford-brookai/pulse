"""Dead-letter table for failed Redpanda webhook publishes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # failed_webhooks — DLQ for Redpanda publish failures
    # Connector writes here on KafkaException; future retry worker drains by retry_count
    op.create_table(
        "failed_webhooks",
        sa.Column("id", sa.Text(), primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("key", sa.Text(), nullable=False),          # POCAR alert_id
        sa.Column("payload", sa.LargeBinary(), nullable=False),  # raw webhook body (bytea)
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    # Retry worker scans by oldest created_at and lowest retry_count
    op.create_index("ix_failed_webhooks_created_at", "failed_webhooks", ["created_at"])
    op.create_index("ix_failed_webhooks_retry_count", "failed_webhooks", ["retry_count"])


def downgrade() -> None:
    op.drop_index("ix_failed_webhooks_retry_count", table_name="failed_webhooks")
    op.drop_index("ix_failed_webhooks_created_at", table_name="failed_webhooks")
    op.drop_table("failed_webhooks")
