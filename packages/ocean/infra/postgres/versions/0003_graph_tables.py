"""Operational data graph tables: patients, signals, alerts, tasks, interactions, outcomes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. patients — root entity; all other tables FK to this
    op.create_table(
        "patients",
        sa.Column("patient_id", sa.Text(), primary_key=True),
        sa.Column("clinic_id", sa.Text(), nullable=False),
        sa.Column("enrollment_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_event_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_patients_clinic_id", "patients", ["clinic_id"])

    # 2. signals — FK → patients
    op.create_table(
        "signals",
        sa.Column("signal_id", sa.Text(), primary_key=True),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anomalous", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name="fk_signals_patient_id"),
    )
    op.create_index("ix_signals_patient_id", "signals", ["patient_id"])
    op.create_index("ix_signals_received_at", "signals", ["received_at"])
    op.create_index("ix_signals_anomalous", "signals", ["anomalous"])

    # 3. alerts — FK → patients
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.Text(), primary_key=True),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("alert_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name="fk_alerts_patient_id"),
    )
    op.create_index("ix_alerts_patient_id", "alerts", ["patient_id"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_index("ix_alerts_status", "alerts", ["status"])

    # 4. tasks — FK → alerts + patients
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("alert_id", sa.Text(), nullable=False),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("assigned_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.alert_id"], name="fk_tasks_alert_id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name="fk_tasks_patient_id"),
    )
    op.create_index("ix_tasks_patient_id", "tasks", ["patient_id"])
    op.create_index("ix_tasks_alert_id", "tasks", ["alert_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    # 5. interactions — FK → tasks + patients
    op.create_table(
        "interactions",
        sa.Column("interaction_id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("interaction_type", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], name="fk_interactions_task_id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name="fk_interactions_patient_id"),
    )
    op.create_index("ix_interactions_task_id", "interactions", ["task_id"])
    op.create_index("ix_interactions_patient_id", "interactions", ["patient_id"])

    # 6. outcomes — FK → interactions + patients
    op.create_table(
        "outcomes",
        sa.Column("outcome_id", sa.Text(), primary_key=True),
        sa.Column("interaction_id", sa.Text(), nullable=False),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("outcome_type", sa.Text(), nullable=False),
        sa.Column("resolution_status", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["interaction_id"],
            ["interactions.interaction_id"],
            name="fk_outcomes_interaction_id",
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name="fk_outcomes_patient_id"),
    )
    op.create_index("ix_outcomes_interaction_id", "outcomes", ["interaction_id"])
    op.create_index("ix_outcomes_patient_id", "outcomes", ["patient_id"])


def downgrade() -> None:
    # Drop in reverse FK dependency order
    op.drop_table("outcomes")
    op.drop_table("interactions")
    op.drop_table("tasks")
    op.drop_table("alerts")
    op.drop_table("signals")
    op.drop_table("patients")
