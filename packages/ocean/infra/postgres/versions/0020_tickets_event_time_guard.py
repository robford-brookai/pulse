"""Add tickets.last_event_at for the ticket status sequence guard (task 3.7).

Same column, same reasoning as 0019: `handle_ticket_updated`'s status write is
guarded on the event envelope's `timestamp`, and that comparison needs a column
holding event time. `tickets` was not in 0019's table list because the wave-2a
guards it shipped ahead of were all in graph-projection and slack-bot; the
control-plane guard was proposed later, by 3.6's audit (Finding 1).

NULL-able, no default: a pre-migration row has no known event time, and the
guard's `IS NULL` branch treats it as always overwritable — correct for rows
written before the guard existed. A `now()` default would populate the column
with processing time, the exact defect the guard removes (`tickets.updated_at`
already demonstrates it, Caveat A).

No index: the guard reads the column on a row already located by the
`ticket_id` primary key.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "last_event_at")
