"""Relay bookkeeping on `ledger.outbox`: backoff schedule, dead-letter marker, last error.

0001 gave the outbox `attempts` and `published_at` — enough to know a row is pending, not enough
to run the relay the distribution spec describes. Three columns close that gap:

- `next_attempt_at` makes exponential backoff durable. Without it a restarted relay retries a
  transiently failing row immediately, and the backoff exists only for as long as the process does.
- `dead_lettered_at` is the DLQ. A row that fails five attempts stays in the outbox and is marked,
  rather than moving to a second table: the event, its subject, its `seq` and its attempt count are
  already here, a move would duplicate all four, and the FK to `ledger.events` would have to be
  duplicated with it. "Depth" is then a count over one partial index, and redrive is the operator
  clearing the marker — a single, runbook-driven UPDATE, never automatic (spec: exhausted retries
  dead-letter loudly).
- `last_error` is why. A DLQ nobody can triage from is a queue, not a dead-letter queue. It holds
  the transport's message — never an envelope, never a payload — so no PHI reaches this column.

`ix_outbox_unpublished` is redefined to exclude dead-lettered rows: it exists to be the relay's
claim path, and a poison row left in it would be rescanned on every pass forever.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        schema="ledger",
    )
    op.add_column(
        "outbox",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        schema="ledger",
    )
    op.add_column("outbox", sa.Column("last_error", sa.Text(), nullable=True), schema="ledger")

    op.drop_index("ix_outbox_unpublished", table_name="outbox", schema="ledger")
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["created_at"],
        schema="ledger",
        postgresql_where=sa.text("published_at IS NULL AND dead_lettered_at IS NULL"),
    )
    # The monitor's query: depth of the dead-letter queue, alarming at >= 1.
    op.create_index(
        "ix_outbox_dead_lettered",
        "outbox",
        ["dead_lettered_at"],
        schema="ledger",
        postgresql_where=sa.text("dead_lettered_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_dead_lettered", table_name="outbox", schema="ledger")
    op.drop_index("ix_outbox_unpublished", table_name="outbox", schema="ledger")
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["created_at"],
        schema="ledger",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_column("outbox", "last_error", schema="ledger")
    op.drop_column("outbox", "dead_lettered_at", schema="ledger")
    op.drop_column("outbox", "next_attempt_at", schema="ledger")
