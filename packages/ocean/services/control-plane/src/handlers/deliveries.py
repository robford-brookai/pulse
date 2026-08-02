"""Control plane handler for delivery notification events.

handle_delivery_notification: Enriches fulfilled delivery events with patient
context from the graph and publishes delivery.notify for slack-bot consumption.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

from src.rules import delivery_channel_for

log = structlog.get_logger()


async def handle_delivery_notification(event_data: dict, session, producer=None) -> None:
    """Handle fulfillment.updated events where status is 'delivered'.

    Enriches with patient context (days since consent, active alerts,
    device history count, device type) and publishes delivery.notify
    to ocean.tickets for slack-bot to render.

    Non-delivered statuses are silently skipped (forward compatible).
    """
    payload = event_data.get("payload", {})
    status = payload.get("status", "")

    if status != "delivered":
        return

    patient_id = payload.get("patient_id", "")
    order_id = payload.get("order_id", "")
    tracking_numbers = payload.get("tracking_numbers", [])
    shipping_option = payload.get("shipping_option", "")
    devices = payload.get("devices", [])
    now = datetime.now(tz=UTC)

    # Extract device type from payload
    device_type = "Unknown device"
    if devices and isinstance(devices, list) and len(devices) > 0:
        device_type = devices[0].get("device_name", "Unknown device") or "Unknown device"

    # Query patient context from graph
    # 1. Days since consent (patients.created_at as proxy)
    days_since_consent = 0
    patient_result = await session.execute(
        sa.text("SELECT created_at FROM patients WHERE patient_id = :patient_id"),
        {"patient_id": patient_id},
    )
    created_at = patient_result.scalar_one_or_none()
    if created_at is not None:
        days_since_consent = (now - created_at).days

    # 2. Active alerts count
    alerts_result = await session.execute(
        sa.text("SELECT COUNT(*) FROM alerts WHERE patient_id = :patient_id AND status != 'resolved'"),
        {"patient_id": patient_id},
    )
    active_alerts_count = alerts_result.scalar_one()

    # 3. Device history count
    device_result = await session.execute(
        sa.text("SELECT COUNT(*) FROM device_associations WHERE patient_id = :patient_id"),
        {"patient_id": patient_id},
    )
    device_history_count = device_result.scalar_one()

    channel = delivery_channel_for()

    log.info(
        "delivery_notification_enriched",
        patient_id=patient_id,
        order_id=order_id,
        device_type=device_type,
        days_since_consent=days_since_consent,
        active_alerts_count=active_alerts_count,
        device_history_count=device_history_count,
    )

    if producer:
        notify_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "delivery.notify",
            "schema_version": "1.0.0",
            "timestamp": now.isoformat(),
            "source_system": "control-plane",
            "entity_id": order_id,
            "entity_type": "fulfillment",
            "correlation_id": event_data.get("correlation_id", ""),
            "payload": {
                "patient_id": patient_id,
                "order_id": order_id,
                "device_type": device_type,
                "days_since_consent": days_since_consent,
                "tracking_numbers": tracking_numbers,
                "shipping_option": shipping_option,
                "active_alerts_count": active_alerts_count,
                "device_history_count": device_history_count,
                "channel": channel,
            },
        }
        await producer.publish("ocean.tickets", notify_event)
