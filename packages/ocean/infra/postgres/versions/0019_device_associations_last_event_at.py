"""Add device_associations.last_event_at, the sequence guard's event-time column.

The two device_associations writers were guarded only against repeat of the same
event id, which prevents a duplicate but not an older event overwriting a newer
one. Neither existing timestamp can carry the guard: associated_at and removed_at
are stamped with the processing clock, so under reordering they encode arrival
order and re-encode the bug. This column holds the envelope's timestamp, fixed
when the event is produced.

Existing rows are left NULL: their event time is unknown, and the guard treats
NULL as "no recorded event time" so the first guarded write still lands.

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
    op.execute(sa.text("ALTER TABLE device_associations ADD COLUMN last_event_at TIMESTAMPTZ"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE device_associations DROP COLUMN last_event_at"))
