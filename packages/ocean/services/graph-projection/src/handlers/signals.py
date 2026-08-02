"""Graph projection handlers for signal events."""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_signal_received(event_data: dict, session) -> None:
    """Project signal.received — INSERT with ON CONFLICT DO UPDATE."""
    payload = event_data.get("payload", {})
    signal_id = event_data.get("entity_id", "")
    received_at = _parse_ts(event_data["timestamp"])

    await session.execute(
        sa.text(
            "INSERT INTO signals "
            "    (signal_id, patient_id, signal_type, value, unit, received_at, anomalous, last_event_id) "
            "VALUES "
            "    (:signal_id, :patient_id, :signal_type, :value, :unit, :received_at, :anomalous, :event_id) "
            "ON CONFLICT (signal_id) DO UPDATE SET "
            "    anomalous = EXCLUDED.anomalous, "
            "    last_event_id = EXCLUDED.last_event_id "
            "WHERE signals.received_at <= EXCLUDED.received_at"
        ),
        {
            "signal_id": signal_id,
            "patient_id": payload.get("patient_id", ""),
            "signal_type": payload.get("signal_type", "unknown"),
            "value": payload.get("value"),
            "unit": payload.get("unit"),
            "received_at": received_at,
            "anomalous": payload.get("anomalous", False),
            "event_id": event_data.get("event_id", ""),
        },
    )
    log.info("signal_projected", signal_id=signal_id)


async def handle_signal_missing(event_data: dict, session) -> None:
    """Project signal.missing — missing signal IS an anomaly."""
    payload = event_data.get("payload", {})
    signal_id = event_data.get("entity_id", "")
    received_at = _parse_ts(event_data["timestamp"])

    await session.execute(
        sa.text(
            "INSERT INTO signals "
            "    (signal_id, patient_id, signal_type, value, unit, received_at, anomalous, last_event_id) "
            "VALUES "
            "    (:signal_id, :patient_id, :signal_type, NULL, NULL, :received_at, true, :event_id) "
            "ON CONFLICT (signal_id) DO UPDATE SET "
            "    anomalous = true, "
            "    last_event_id = EXCLUDED.last_event_id"
        ),
        {
            "signal_id": signal_id,
            "patient_id": payload.get("patient_id", ""),
            "signal_type": payload.get("signal_type", "missing"),
            "received_at": received_at,
            "event_id": event_data.get("event_id", ""),
        },
    )
    log.info("signal_missing_projected", signal_id=signal_id)


async def handle_signal_anomalous(event_data: dict, session) -> None:
    """Project signal.anomalous — mark existing signal anomalous=True."""
    signal_id = event_data.get("entity_id", "")
    await session.execute(
        sa.text("UPDATE signals SET anomalous=true, last_event_id=:event_id WHERE signal_id=:signal_id"),
        {"signal_id": signal_id, "event_id": event_data.get("event_id", "")},
    )
    log.info("signal_anomalous_projected", signal_id=signal_id)
