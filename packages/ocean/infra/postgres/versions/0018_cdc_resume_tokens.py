"""Add cdc_resume_tokens table for Change-Data-Capture checkpoint storage.

The mongodb-connector CollectionWatcher persists its MongoDB change-stream
resume token here after each published event. On restart the watcher reads
this token so it resumes from where it left off — no replayed events, no
missed events.

Revision ID: 0018
Revises: 0017
Create Date: 2026-03-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE TABLE cdc_resume_tokens ("
            "  collection_name TEXT PRIMARY KEY,"
            "  resume_token JSONB NOT NULL,"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS cdc_resume_tokens"))
