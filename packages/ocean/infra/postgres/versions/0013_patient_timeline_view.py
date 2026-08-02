"""Patient timeline consolidated view across all entity tables.

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW patient_timeline AS
              SELECT patient_id, 'alert' AS event_type, alert_id AS event_id, status,
                     alert_type || ' ' || severity || ' -- ' || status AS summary, created_at
              FROM alerts
              UNION ALL
              SELECT patient_id, 'task' AS event_type, task_id AS event_id, status,
                     task_type || ' [' || priority || '] -- ' || status AS summary, created_at
              FROM tasks
              UNION ALL
              SELECT patient_id, 'ticket' AS event_type, ticket_id AS event_id, status,
                     COALESCE(human_id, ticket_id) || ' ' || category || ' -- ' || status AS summary, created_at
              FROM tickets WHERE patient_id IS NOT NULL
              UNION ALL
              SELECT patient_id, 'fulfillment' AS event_type, order_id AS event_id, status,
                     'Order ' || COALESCE(shipping_option, '') || ' -- ' || status AS summary, created_at
              FROM fulfillments
              UNION ALL
              SELECT patient_id, 'return' AS event_type, return_id AS event_id, status,
                     'Return ' || COALESCE(reason, '') || ' -- ' || status AS summary, created_at
              FROM returns
              UNION ALL
              SELECT patient_id, 'device' AS event_type, id::text AS event_id, status,
                     COALESCE(device_name, '') || ' ' || device_id || ' -- ' || status AS summary,
                     associated_at AS created_at
              FROM device_associations
              UNION ALL
              SELECT patient_id, 'interaction' AS event_type, interaction_id AS event_id,
                     COALESCE(outcome, 'pending') AS status,
                     interaction_type || ' -- ' || COALESCE(outcome, 'pending') AS summary,
                     COALESCE(started_at, completed_at) AS created_at
              FROM interactions
              UNION ALL
              SELECT patient_id, 'signal' AS event_type, signal_id AS event_id,
                     CASE WHEN anomalous THEN 'anomalous' ELSE 'normal' END AS status,
                     signal_type || ' = ' || COALESCE(value::text, 'null') || ' ' || COALESCE(unit, '') AS summary,
                     received_at AS created_at
              FROM signals
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS patient_timeline"))
