"""Add ticket_id column to returns table for RMA-ticket linking.

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE returns ADD COLUMN ticket_id TEXT REFERENCES tickets(ticket_id)"))
    op.execute(sa.text("CREATE INDEX ix_returns_ticket_id ON returns(ticket_id)"))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX ix_returns_ticket_id"))
    op.execute(sa.text("ALTER TABLE returns DROP COLUMN ticket_id"))
