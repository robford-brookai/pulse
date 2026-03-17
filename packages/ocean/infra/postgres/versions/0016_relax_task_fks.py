"""Relax foreign key constraints on event-projected tables.

All entity tables are populated by independent Kafka consumers
(control-plane, graph-projection, slack-bot). Event ordering across
consumers is not guaranteed, so a child row may arrive before its
parent. Drop all inter-entity FKs — data integrity is guaranteed by
the event stream (eventually consistent), not referential constraints.

Hasura catalog FKs are left intact.

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

# All non-Hasura FK constraints on event-projected tables
FK_CONSTRAINTS = [
    # tasks
    ("tasks", "fk_tasks_alert_id", "alert_id", "alerts", "alert_id"),
    ("tasks", "fk_tasks_patient_id", "patient_id", "patients", "patient_id"),
    # alerts
    ("alerts", "fk_alerts_patient_id", "patient_id", "patients", "patient_id"),
    # signals
    ("signals", "fk_signals_patient_id", "patient_id", "patients", "patient_id"),
    # interactions
    ("interactions", "fk_interactions_patient_id", "patient_id", "patients", "patient_id"),
    ("interactions", "fk_interactions_task_id", "task_id", "tasks", "task_id"),
    # outcomes
    ("outcomes", "fk_outcomes_patient_id", "patient_id", "patients", "patient_id"),
    ("outcomes", "fk_outcomes_interaction_id", "interaction_id", "interactions", "interaction_id"),
    # ai_drafts
    ("ai_drafts", "ai_drafts_task_id_fkey", "task_id", "tasks", "task_id"),
    # bridge tables
    ("alert_tasks", "alert_tasks_alert_id_fkey", "alert_id", "alerts", "alert_id"),
    ("alert_tasks", "alert_tasks_task_id_fkey", "task_id", "tasks", "task_id"),
    ("ticket_tasks", "ticket_tasks_task_id_fkey", "task_id", "tasks", "task_id"),
    ("ticket_tasks", "ticket_tasks_ticket_id_fkey", "ticket_id", "tickets", "ticket_id"),
    ("ticket_alerts", "ticket_alerts_alert_id_fkey", "alert_id", "alerts", "alert_id"),
    ("ticket_alerts", "ticket_alerts_ticket_id_fkey", "ticket_id", "tickets", "ticket_id"),
    # tickets
    ("tickets", "tickets_patient_id_fkey", "patient_id", "patients", "patient_id"),
    # fulfillments / returns / devices
    ("fulfillments", "fulfillments_patient_id_fkey", "patient_id", "patients", "patient_id"),
    ("returns", "returns_patient_id_fkey", "patient_id", "patients", "patient_id"),
    ("returns", "returns_ticket_id_fkey", "ticket_id", "tickets", "ticket_id"),
    ("device_associations", "device_associations_patient_id_fkey", "patient_id", "patients", "patient_id"),
]


def upgrade() -> None:
    for table, constraint, _, _, _ in FK_CONSTRAINTS:
        op.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))


def downgrade() -> None:
    for table, constraint, column, ref_table, ref_column in FK_CONSTRAINTS:
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column})"
            )
        )
