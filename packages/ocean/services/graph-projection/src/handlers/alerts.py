"""Graph projection handlers for alert events."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to timezone-aware datetime."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_alert_created(event_data: dict, session) -> None:
    """Project alert.created into patients (bootstrap) + alerts + audit_log.

    Three operations within a single transaction:
    1. Patient bootstrap — INSERT ... ON CONFLICT DO NOTHING (prevents FK violation)
    2. Alert upsert — INSERT ... ON CONFLICT DO UPDATE SET ... WHERE updated_at guard
    3. Audit log write — AUDIT-01 compliance
    """
    payload = event_data.get("payload", {})
    patient_id = payload.get("patient_id", event_data.get("entity_id", ""))
    clinic_id = payload.get("clinic_id", "unknown")
    ts = _parse_ts(event_data["timestamp"])
    now = datetime.now(tz=UTC)

    # STEP 1: Patient bootstrap — ensure FK constraint is satisfied
    await session.execute(
        sa.text(
            "INSERT INTO patients (patient_id, clinic_id, enrollment_status, updated_at) "
            "VALUES (:patient_id, :clinic_id, 'pending', :ts) "
            "ON CONFLICT (patient_id) DO NOTHING"
        ),
        {"patient_id": patient_id, "clinic_id": clinic_id, "ts": ts},
    )

    # STEP 2: Alert upsert with updated_at guard for idempotency
    alert_id = event_data.get("entity_id", payload.get("alert_id", ""))
    await session.execute(
        sa.text(
            "INSERT INTO alerts "
            "    (alert_id, patient_id, alert_type, severity, status, "
            "     source_system, created_at, updated_at, correlation_id, last_event_id) "
            "VALUES "
            "    (:alert_id, :patient_id, :alert_type, :severity, 'open', "
            "     :source_system, :created_at, :updated_at, :correlation_id, :event_id) "
            "ON CONFLICT (alert_id) DO UPDATE SET "
            "    status = EXCLUDED.status, "
            "    updated_at = EXCLUDED.updated_at, "
            "    last_event_id = EXCLUDED.last_event_id "
            "WHERE alerts.updated_at < EXCLUDED.updated_at"
        ),
        {
            "alert_id": alert_id,
            "patient_id": patient_id,
            "alert_type": payload.get("alert_type", "unknown"),
            "severity": payload.get("severity", "unknown"),
            "source_system": event_data.get("source_system", "unknown"),
            "created_at": ts,
            "updated_at": now,
            "correlation_id": event_data.get("correlation_id", ""),
            "event_id": event_data.get("event_id", ""),
        },
    )

    # STEP 3: Audit log write (AUDIT-01 compliance)
    await session.execute(
        sa.text(
            "INSERT INTO audit_log "
            "(audit_id, event_id, action_type, actor_id, source_system, entity_type, entity_id, timestamp, detail) "
            "VALUES (:audit_id, :event_id, :action_type, :actor_id, :source_system, :entity_type, :entity_id, :timestamp, :detail)"
        ),
        {
            "audit_id": str(uuid.uuid4()),
            "event_id": event_data.get("event_id", ""),
            "action_type": "graph_upsert",
            "actor_id": "system",
            "source_system": event_data.get("source_system", "unknown"),
            "entity_type": "alert",
            "entity_id": alert_id,
            "timestamp": now,
            "detail": json.dumps({"alert_type": payload.get("alert_type")}),
        },
    )

    log.info("alert_projected", alert_id=alert_id, patient_id=patient_id)


async def handle_alert_claimed(event_data: dict, session) -> None:
    """Project alert.claimed — update status to 'claimed'."""
    now = datetime.now(tz=UTC)
    alert_id = event_data.get("entity_id", "")
    await session.execute(
        sa.text(
            "UPDATE alerts SET status='claimed', updated_at=:updated_at, last_event_id=:event_id "
            "WHERE alert_id=:alert_id"
        ),
        {"alert_id": alert_id, "updated_at": now, "event_id": event_data.get("event_id", "")},
    )
    log.info("alert_claimed", alert_id=alert_id)


async def handle_alert_resolved(event_data: dict, session) -> None:
    """Project alert.resolved — update status to 'resolved'."""
    now = datetime.now(tz=UTC)
    alert_id = event_data.get("entity_id", "")
    await session.execute(
        sa.text(
            "UPDATE alerts SET status='resolved', updated_at=:updated_at, last_event_id=:event_id "
            "WHERE alert_id=:alert_id"
        ),
        {"alert_id": alert_id, "updated_at": now, "event_id": event_data.get("event_id", "")},
    )
    log.info("alert_resolved", alert_id=alert_id)
