"""Identity registry and the review queue's drain shape — the affordances task 4.1's reads need.

Migration 0001 gave the ledger its six tables, but nothing there answers "who holds
`(system, value)`?" or "which persons share this normalized composite?" — the two lookups the
deterministic matcher (S1.4) runs before every `received → resolved` declaration. Two tables and
one column:

- `external_identifiers` is the registry ExternalIdentifier has always been in the object model
  (`design/migration/rpc-object-model-assessment.md` §identifiers: registry child, not a
  state-bearing subject). Its primary key **is** the uniqueness rule: `(system, value)` resolves to
  at most one person, enforced by the store rather than by the resolver remembering to check.
  Append-only for the service role, like `events`: a binding is corrected by `merge_person`, never
  by an UPDATE that would silently move an MRN between patients.
- `person_match_keys` carries the composite the matcher falls back to when no identifier matches.
  It stores a **digest**, never the demographics: the composite is last name + DOB + sex +
  first-initial (PHI), and a `[0-9a-f]{64}` check constraint is what keeps the readable form out of
  the ledger by construction. Normalization and hashing belong to the matcher; the ledger indexes
  the result. One person may carry several digests (a name change mints another), so the key is the
  pair.
- `review_queue.resolution_event_id` closes the queue's exit: a row leaves only by naming the
  declared resolution that drained it, and the check constraint makes "resolved" and "names its
  resolution" the same state. The partial unique index makes a second pending review for one
  subject impossible, so a retried quarantine cannot double-enqueue.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SERVICE_ROLE = "pulse_ledger_service"

ACTOR_TYPES = ("human", "agent", "system")

#: A normalized-composite digest: lowercase hex sha256, and nothing that reads as demographics.
MATCH_KEY_FORMAT = "^[0-9a-f]{64}$"


def upgrade() -> None:
    op.create_table(
        "external_identifiers",
        sa.Column("system", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), primary_key=True),
        sa.Column("person_key", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "actor_type IN (" + ", ".join(f"'{value}'" for value in ACTOR_TYPES) + ")",
            name="ck_external_identifiers_actor_type",
        ),
        sa.CheckConstraint("btrim(system) <> ''", name="ck_external_identifiers_system_present"),
        sa.CheckConstraint("btrim(value) <> ''", name="ck_external_identifiers_value_present"),
        sa.CheckConstraint("btrim(person_key) <> ''", name="ck_external_identifiers_person_key_present"),
        schema="ledger",
    )
    # The reverse direction: every identifier one person holds, for the resolver's evidence.
    op.create_index("ix_external_identifiers_person", "external_identifiers", ["person_key"], schema="ledger")

    op.create_table(
        "person_match_keys",
        sa.Column("person_key", sa.Text(), primary_key=True),
        sa.Column("match_key", sa.Text(), primary_key=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"match_key ~ '{MATCH_KEY_FORMAT}'", name="ck_person_match_keys_digest"),
        sa.CheckConstraint("btrim(person_key) <> ''", name="ck_person_match_keys_person_key_present"),
        schema="ledger",
    )
    # Candidate retrieval reads by digest, so the digest leads the index.
    op.create_index("ix_person_match_keys_lookup", "person_match_keys", ["match_key"], schema="ledger")

    op.add_column(
        "review_queue",
        sa.Column("resolution_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="ledger",
    )
    op.create_foreign_key(
        "fk_review_queue_resolution_event",
        "review_queue",
        "events",
        ["resolution_event_id"],
        ["event_id"],
        source_schema="ledger",
        referent_schema="ledger",
    )
    op.create_check_constraint(
        "ck_review_queue_resolution_declared",
        "review_queue",
        "pending OR (resolved_at IS NOT NULL AND resolution_event_id IS NOT NULL)",
        schema="ledger",
    )
    op.create_index(
        "uq_review_queue_one_pending_per_subject",
        "review_queue",
        ["subject_type", "subject_key"],
        unique=True,
        schema="ledger",
        postgresql_where=sa.text("pending"),
    )

    # A binding is append-only for the service: rebinding an identifier is a `merge_person`
    # declaration, not an in-place move of an MRN from one patient to another.
    op.execute(f"GRANT SELECT, INSERT ON ledger.external_identifiers TO {SERVICE_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON ledger.person_match_keys TO {SERVICE_ROLE}")


def downgrade() -> None:
    op.drop_index("uq_review_queue_one_pending_per_subject", "review_queue", schema="ledger")
    op.drop_constraint("ck_review_queue_resolution_declared", "review_queue", schema="ledger", type_="check")
    op.drop_constraint("fk_review_queue_resolution_event", "review_queue", schema="ledger", type_="foreignkey")
    op.drop_column("review_queue", "resolution_event_id", schema="ledger")
    op.drop_table("person_match_keys", schema="ledger")
    op.drop_table("external_identifiers", schema="ledger")
