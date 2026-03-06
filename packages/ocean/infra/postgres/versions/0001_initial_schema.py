"""Initial Ocean schema: events and audit_log tables.

Revision ID: 0001
Revises:
Create Date: 2026-03-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Events table — append-only ledger of all Ocean events
    op.create_table(
        "events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="1.0.0"),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_events_entity", "events", ["entity_type", "entity_id"])
    op.create_index("ix_events_timestamp", "events", ["timestamp"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_source_system", "events", ["source_system"])

    # Audit log — append-only HIPAA audit trail per 45 C.F.R. § 164.312(b)
    op.create_table(
        "audit_log",
        sa.Column("audit_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=True),  # nullable for non-event actions
        sa.Column("action_type", sa.Text(), nullable=False),  # "event.ingested" | "task.state_changed"
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_event_id", "audit_log", ["event_id"])

    # Enforce append-only on audit_log at the database level (AUDIT-02)
    # The ocean application user cannot UPDATE or DELETE audit_log rows.
    op.execute("REVOKE UPDATE, DELETE ON TABLE audit_log FROM PUBLIC;")


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("events")
