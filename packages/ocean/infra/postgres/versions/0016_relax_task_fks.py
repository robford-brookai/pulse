"""Relax foreign key constraints on tasks table.

Tasks are created by control-plane consuming ocean.alerts, but the
referenced alerts and patients rows are created by graph-projection
consuming the same events. Since both are independent consumers,
the graph-projection insert may lag behind control-plane, causing
FK violations. Drop the FKs since the data is eventually consistent
(all rows arrive from the same event stream).

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_alert_id"))
    op.execute(sa.text("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_patient_id"))


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE tasks ADD CONSTRAINT fk_tasks_alert_id "
            "FOREIGN KEY (alert_id) REFERENCES alerts(alert_id)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE tasks ADD CONSTRAINT fk_tasks_patient_id "
            "FOREIGN KEY (patient_id) REFERENCES patients(patient_id)"
        )
    )
