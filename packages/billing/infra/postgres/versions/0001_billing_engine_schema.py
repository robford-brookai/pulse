"""The `billing_engine` schema — per connector-pattern design.md decision 5.

Two tables, both rebuildable from the bus at any time and never a source of truth
(design.md risk "Engine state store becomes a shadow ledger"; enforced separately by the
shadow-ledger gate in ``tests/test_shadow_ledger_gate.py``, which pins that no state-of-record
read ever targets this schema):

- `subject_facts` holds the engine's per-subject fact snapshot, one row per subject, folded
  from consumed ledger events (task 3.2). `last_event_id` is the per-subject high-water mark
  the fold uses to apply each event at most once.
- `evaluations` is the append log of every rule evaluation the engine has run — one row per
  declared verdict event, `declared_event_id` unique — so re-evaluating unchanged facts is
  idempotent (no new row: "Re-evaluating unchanged facts declares nothing new", billing-engine
  spec) and the reconciliation sweep (wave 3) has a full history to compare against the mart
  over matching fact windows, not just the latest outcome per verdict type.

This store lives in its own database (`billing_engine`), not the ledger's — decision 5 is
explicit that the engine's credential is "not the ledger schema" — so a leaked or over-scoped
billing-engine credential can never reach `ledger.*`, and vice versa.

Revision ID: 0001
Revises:
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SERVICE_ROLE = "billing_engine_service"


def upgrade() -> None:
    op.execute("CREATE SCHEMA billing_engine")

    op.create_table(
        "subject_facts",
        sa.Column("subject_type", sa.Text(), primary_key=True),
        sa.Column("subject_key", sa.Text(), primary_key=True),
        sa.Column("facts", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        schema="billing_engine",
    )

    op.create_table(
        "evaluations",
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=False),
        sa.Column("verdict_type", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("declared_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("declared_event_id", name="uq_evaluations_declared_event"),
        schema="billing_engine",
    )
    # The re-evaluation idempotency check and the reconciliation sweep both look up the most
    # recent evaluation for a (subject, verdict_type).
    op.create_index(
        "ix_evaluations_subject_verdict_as_of",
        "evaluations",
        ["subject_type", "subject_key", "verdict_type", "as_of"],
        schema="billing_engine",
    )

    # Cluster-level, so create only if absent (a shared dev cluster may already carry it from
    # another database).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{SERVICE_ROLE}') THEN
                CREATE ROLE {SERVICE_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA billing_engine TO {SERVICE_ROLE}")
    # Both tables are upsertable snapshots/logs the service folds into and evaluates from — no
    # DELETE: a rebuild-from-bus is an operator-driven drop/recreate, never a per-row delete the
    # service itself performs.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON billing_engine.subject_facts TO {SERVICE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON billing_engine.evaluations TO {SERVICE_ROLE}")


def downgrade() -> None:
    op.drop_table("evaluations", schema="billing_engine")
    op.drop_table("subject_facts", schema="billing_engine")
    op.execute("DROP SCHEMA billing_engine")
    op.execute(f"DROP ROLE IF EXISTS {SERVICE_ROLE}")
