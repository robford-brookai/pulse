"""Add last_event_at event-time columns for the wave-2a sequence guards.

Each wave-2a sequence guard compares the event envelope's `timestamp`
(ocean_events.BaseEvent.timestamp, UTC ISO 8601) against the value stored by
whichever event last touched the row. That comparison needs a column to hold
event time, and every guarded table needs the same one. This migration adds it
once, ahead of the guards, so the four guard changes stay independent.

The column is NULL-able and carries no default. A pre-migration row has no
known event time, and a guard written as

    WHERE <table>.last_event_at IS NULL OR <table>.last_event_at < EXCLUDED.last_event_at

then treats such a row as always overwritable — correct for backfilled state. A
`now()` default would populate the column with processing time, which is the
exact defect wave 2a exists to remove.

No index is added. Every guard reads the column on a row already located by an
existing key: interactions and signals by primary key, device_associations by
its UNIQUE (patient_id, device_id), slack_messages by idx_slack_messages_task_id
or idx_slack_messages_ts. An index on last_event_at would be written on every
projection write and read by nothing.

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

# One column, identical on every table a wave-2a guard protects. `outcomes` is
# absent on purpose: it is append-only (ON CONFLICT (outcome_id) DO NOTHING)
# and has nothing to overwrite.
GUARDED_TABLES = ("interactions", "device_associations", "signals", "slack_messages")


def upgrade() -> None:
    for table in GUARDED_TABLES:
        op.add_column(table, sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in reversed(GUARDED_TABLES):
        op.drop_column(table, "last_event_at")
