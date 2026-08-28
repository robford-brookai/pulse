"""The `ledger` schema — per pulse-ledger-core design decision 1.

Six tables, one write posture:

- `events` is the append-only bitemporal record: `effective_at` (when the fact was true)
  vs `recorded_at` (server-set, when the ledger learned it), `evidence_class` E0-E4 with
  E3 required to carry its interpolation interval bounds, `epoch` declared vs
  reconstructed, and correction by `reverses_event_id` — never by UPDATE.
- `current_state` holds exactly one row per subject (PK on subject_type + subject_key),
  co-committed with the event that changed it; `last_event_id` FK is the shape that ties
  a state row to a committed event.
- `idempotency_keys` maps key → event_id and is kept forever (D16).
- `outbox` carries a per-subject `seq` (unique per subject) for ordered relay (D17).
- `writer_state` is the cursor facility downstream writers resume from.
- `review_queue` holds quarantined subjects awaiting human adjudication.

Immutability is enforced in the store, not by convention: the service role is granted
INSERT and SELECT on `events`, and UPDATE/DELETE are explicitly revoked — this is what
keeps the warehouse detector Q_EVENT_MUTATIONS empty by construction. The role is
created here if absent (cluster-level object, so it may pre-exist) and dropped on
downgrade.

Revision ID: 0001
Revises:
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SERVICE_ROLE = "pulse_ledger_service"

# The six subject grains of object model v0.7.
SUBJECT_TYPES = ("referral", "consent", "enrollment", "billing_episode", "device", "contract")
EVIDENCE_CLASSES = ("E0", "E1", "E2", "E3", "E4")
EPOCHS = ("declared", "reconstructed")
ACTOR_TYPES = ("human", "agent", "system")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.execute("CREATE SCHEMA ledger")

    op.create_table(
        "events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("producer", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("actor_authority", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_class", sa.Text(), nullable=False, server_default=sa.text("'E0'")),
        sa.Column("evidence_bound_lower", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_bound_upper", sa.DateTime(timezone=True), nullable=True),
        sa.Column("epoch", sa.Text(), nullable=False, server_default=sa.text("'declared'")),
        sa.Column("reverses_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint(_one_of("subject_type", SUBJECT_TYPES), name="ck_events_subject_type"),
        sa.CheckConstraint(_one_of("actor_type", ACTOR_TYPES), name="ck_events_actor_type"),
        sa.CheckConstraint(_one_of("evidence_class", EVIDENCE_CLASSES), name="ck_events_evidence_class"),
        sa.CheckConstraint(_one_of("epoch", EPOCHS), name="ck_events_epoch"),
        sa.CheckConstraint(
            "evidence_class <> 'E3' OR (evidence_bound_lower IS NOT NULL AND evidence_bound_upper IS NOT NULL)",
            name="ck_events_e3_bounds",
        ),
        sa.CheckConstraint(
            "evidence_bound_lower IS NULL OR evidence_bound_upper IS NULL"
            " OR evidence_bound_lower <= evidence_bound_upper",
            name="ck_events_bounds_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_event_id"],
            ["ledger.events.event_id"],
            name="fk_events_reverses_event",
        ),
        schema="ledger",
    )
    # The fold order every reader and the warehouse re-derivation use: effective_at, ties
    # by recorded_at, scoped to one subject.
    op.create_index(
        "ix_events_subject_fold",
        "events",
        ["subject_type", "subject_key", "effective_at", "recorded_at"],
        schema="ledger",
    )

    op.create_table(
        "current_state",
        sa.Column("subject_type", sa.Text(), primary_key=True),
        sa.Column("subject_key", sa.Text(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(_one_of("subject_type", SUBJECT_TYPES), name="ck_current_state_subject_type"),
        sa.ForeignKeyConstraint(
            ["last_event_id"],
            ["ledger.events.event_id"],
            name="fk_current_state_last_event",
        ),
        schema="ledger",
    )
    op.create_index("ix_current_state_by_state", "current_state", ["subject_type", "state"], schema="ledger")

    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["event_id"], ["ledger.events.event_id"], name="fk_idempotency_keys_event"),
        schema="ledger",
    )

    op.create_table(
        "outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subject_type", "subject_key", "seq", name="uq_outbox_subject_seq"),
        sa.ForeignKeyConstraint(["event_id"], ["ledger.events.event_id"], name="fk_outbox_event"),
        schema="ledger",
    )
    # The relay scans only what is not yet published, in arrival order.
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["created_at"],
        schema="ledger",
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "writer_state",
        sa.Column("writer_id", sa.Text(), primary_key=True),
        sa.Column("cursor", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ledger",
    )

    op.create_table(
        "review_queue",
        sa.Column(
            "review_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=False),
        sa.Column("hold_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_one_of("subject_type", SUBJECT_TYPES), name="ck_review_queue_subject_type"),
        sa.ForeignKeyConstraint(["hold_event_id"], ["ledger.events.event_id"], name="fk_review_queue_hold_event"),
        schema="ledger",
    )
    op.create_index(
        "ix_review_queue_pending",
        "review_queue",
        ["created_at"],
        schema="ledger",
        postgresql_where=sa.text("pending"),
    )

    # Roles are cluster-level: create only if absent, so a shared dev cluster where
    # another database already carries the role upgrades cleanly.
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
    op.execute(f"GRANT USAGE ON SCHEMA ledger TO {SERVICE_ROLE}")
    # events is append-only for the service: the revoke is redundant with never granting
    # UPDATE/DELETE, and stated anyway so the posture survives a later blanket grant.
    op.execute(f"GRANT SELECT, INSERT ON ledger.events TO {SERVICE_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON ledger.events FROM {SERVICE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ledger.current_state TO {SERVICE_ROLE}")
    # idempotency keys are kept forever (D16): no UPDATE, no DELETE.
    op.execute(f"GRANT SELECT, INSERT ON ledger.idempotency_keys TO {SERVICE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ledger.outbox TO {SERVICE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ledger.writer_state TO {SERVICE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ledger.review_queue TO {SERVICE_ROLE}")


def downgrade() -> None:
    op.drop_table("review_queue", schema="ledger")
    op.drop_table("writer_state", schema="ledger")
    op.drop_table("outbox", schema="ledger")
    op.drop_table("idempotency_keys", schema="ledger")
    op.drop_table("current_state", schema="ledger")
    op.drop_table("events", schema="ledger")
    op.execute("DROP SCHEMA ledger")
    op.execute(f"DROP ROLE IF EXISTS {SERVICE_ROLE}")
