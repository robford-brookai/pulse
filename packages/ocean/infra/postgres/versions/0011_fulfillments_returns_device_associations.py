"""Fulfillments, returns, and device_associations tables.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Fulfillments table ---
    op.execute(
        sa.text(
            """
            CREATE TABLE fulfillments (
                order_id        TEXT PRIMARY KEY,
                patient_id      TEXT REFERENCES patients(patient_id),
                status          TEXT NOT NULL DEFAULT 'orderPlaced',
                shipping_option TEXT,
                tracking_numbers JSONB DEFAULT '[]'::jsonb,
                order_items     JSONB DEFAULT '[]'::jsonb,
                devices         JSONB DEFAULT '[]'::jsonb,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_event_id   TEXT
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_fulfillments_patient_id ON fulfillments(patient_id)"))
    op.execute(sa.text("CREATE INDEX ix_fulfillments_status ON fulfillments(status)"))

    # --- Returns table ---
    op.execute(
        sa.text(
            """
            CREATE TABLE returns (
                return_id       TEXT PRIMARY KEY,
                patient_id      TEXT REFERENCES patients(patient_id),
                device_id       TEXT,
                order_id        TEXT,
                status          TEXT NOT NULL,
                reason          TEXT,
                raw_payload     JSONB DEFAULT '{}'::jsonb,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_event_id   TEXT
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_returns_patient_id ON returns(patient_id)"))
    op.execute(sa.text("CREATE INDEX ix_returns_order_id ON returns(order_id)"))
    op.execute(sa.text("CREATE INDEX ix_returns_status ON returns(status)"))

    # --- Device associations table ---
    op.execute(
        sa.text(
            """
            CREATE TABLE device_associations (
                id              SERIAL PRIMARY KEY,
                patient_id      TEXT NOT NULL REFERENCES patients(patient_id),
                device_id       TEXT NOT NULL,
                device_name     TEXT,
                status          TEXT NOT NULL DEFAULT 'active',
                associated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                removed_at      TIMESTAMPTZ,
                last_event_id   TEXT,
                UNIQUE (patient_id, device_id)
            )
            """
        )
    )
    op.execute(
        sa.text("CREATE INDEX ix_device_associations_patient_id ON device_associations(patient_id)")
    )
    op.execute(
        sa.text("CREATE INDEX ix_device_associations_device_id ON device_associations(device_id)")
    )
    op.execute(
        sa.text("CREATE INDEX ix_device_associations_status ON device_associations(status)")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE device_associations"))
    op.execute(sa.text("DROP TABLE returns"))
    op.execute(sa.text("DROP TABLE fulfillments"))
