"""Tickets, bridge tables, sequences, nullable alert_id, priority migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Per-category sequences for human-readable ticket IDs ---
    op.execute(sa.text("CREATE SEQUENCE ticket_seq_device_issue START 1"))
    op.execute(sa.text("CREATE SEQUENCE ticket_seq_patient_activation START 1"))
    op.execute(sa.text("CREATE SEQUENCE ticket_seq_clinical_support START 1"))
    op.execute(sa.text("CREATE SEQUENCE ticket_seq_engineering_it START 1"))

    # --- Tickets table ---
    op.execute(
        sa.text(
            """
            CREATE TABLE tickets (
                ticket_id       TEXT PRIMARY KEY,
                human_id        TEXT NOT NULL UNIQUE,
                category        TEXT NOT NULL,
                priority        TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'open',
                patient_id      TEXT REFERENCES patients(patient_id),
                description     TEXT NOT NULL,
                waiting_reason  TEXT,
                created_at      TIMESTAMPTZ NOT NULL,
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                correlation_id  TEXT NOT NULL,
                last_event_id   TEXT
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX ix_tickets_patient_id ON tickets(patient_id)"))
    op.execute(sa.text("CREATE INDEX ix_tickets_status ON tickets(status)"))
    op.execute(sa.text("CREATE INDEX ix_tickets_category ON tickets(category)"))
    op.execute(sa.text("CREATE UNIQUE INDEX ix_tickets_human_id ON tickets(human_id)"))
    op.execute(sa.text("CREATE INDEX ix_tickets_priority ON tickets(priority)"))

    # --- Bridge tables ---
    op.execute(
        sa.text(
            """
            CREATE TABLE ticket_tasks (
                ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id),
                task_id     TEXT NOT NULL REFERENCES tasks(task_id),
                linked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (ticket_id, task_id)
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TABLE alert_tasks (
                alert_id    TEXT NOT NULL REFERENCES alerts(alert_id),
                task_id     TEXT NOT NULL REFERENCES tasks(task_id),
                linked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (alert_id, task_id)
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TABLE ticket_alerts (
                ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id),
                alert_id    TEXT NOT NULL REFERENCES alerts(alert_id),
                linked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (ticket_id, alert_id)
            )
            """
        )
    )

    # --- Make tasks.alert_id nullable ---
    op.alter_column("tasks", "alert_id", nullable=True)

    # --- Backfill alert_tasks bridge from existing task-alert relationships ---
    op.execute(
        sa.text(
            """
            INSERT INTO alert_tasks (alert_id, task_id, linked_at)
            SELECT alert_id, task_id, created_at
            FROM tasks
            WHERE alert_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )

    # --- Migrate priority values to unified scale ---
    op.execute(
        sa.text(
            """
            UPDATE alerts SET severity = CASE severity
                WHEN 'urgent' THEN 'critical'
                WHEN 'routine' THEN 'medium'
                ELSE severity
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE tasks SET priority = CASE priority
                WHEN 'urgent' THEN 'critical'
                WHEN 'routine' THEN 'medium'
                ELSE priority
            END
            """
        )
    )


def downgrade() -> None:
    # Reverse priority migration
    op.execute(
        sa.text(
            """
            UPDATE tasks SET priority = CASE priority
                WHEN 'critical' THEN 'urgent'
                WHEN 'medium' THEN 'routine'
                ELSE priority
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE alerts SET severity = CASE severity
                WHEN 'critical' THEN 'urgent'
                WHEN 'medium' THEN 'routine'
                ELSE severity
            END
            """
        )
    )

    # Restore tasks.alert_id NOT NULL (will fail if any NULLs exist)
    op.alter_column("tasks", "alert_id", nullable=False)

    # Drop bridge tables
    op.execute(sa.text("DROP TABLE ticket_alerts"))
    op.execute(sa.text("DROP TABLE alert_tasks"))
    op.execute(sa.text("DROP TABLE ticket_tasks"))

    # Drop tickets table
    op.execute(sa.text("DROP TABLE tickets"))

    # Drop sequences
    op.execute(sa.text("DROP SEQUENCE ticket_seq_engineering_it"))
    op.execute(sa.text("DROP SEQUENCE ticket_seq_clinical_support"))
    op.execute(sa.text("DROP SEQUENCE ticket_seq_patient_activation"))
    op.execute(sa.text("DROP SEQUENCE ticket_seq_device_issue"))
