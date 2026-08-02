"""Add interactions.last_event_at — the event-time sequence-guard column.

Delivery is unordered, so the call outcome projections must compare the
envelope timestamp of the incoming event against the envelope timestamp of the
event that last wrote the row. No such column existed: `completed_at` and
`started_at` are both written with the processing clock, and under reordering a
processing-time comparison encodes arrival order — the very bug the guard
exists to fix.

Nullable and backfilled to NULL: rows written before this migration have no
recorded event time. `handlers/sequence.py` treats NULL as "unknown, let the
write through", so the first guarded event to touch a legacy row adopts it.

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
    op.execute(sa.text("ALTER TABLE interactions ADD COLUMN last_event_at TIMESTAMPTZ"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE interactions DROP COLUMN IF EXISTS last_event_at"))
