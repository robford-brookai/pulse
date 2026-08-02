"""Graph projection handlers for Impilo logistics events.

Handles fulfillment, return, and device association lifecycle events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


async def handle_fulfillment_updated(event_data: dict, session) -> None:
    """Project fulfillment.updated -- upsert fulfillments row by order_id."""
    payload = event_data.get("payload", {})
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO fulfillments "
            "  (order_id, patient_id, status, shipping_option, "
            "   tracking_numbers, order_items, devices, "
            "   created_at, updated_at, last_event_id) "
            "VALUES "
            "  (:order_id, :patient_id, :status, :shipping_option, "
            "   :tracking_numbers::jsonb, :order_items::jsonb, :devices::jsonb, "
            "   :created_at, :updated_at, :event_id) "
            "ON CONFLICT (order_id) DO UPDATE SET "
            "  status = EXCLUDED.status, "
            "  shipping_option = EXCLUDED.shipping_option, "
            "  tracking_numbers = EXCLUDED.tracking_numbers, "
            "  order_items = EXCLUDED.order_items, "
            "  devices = EXCLUDED.devices, "
            "  updated_at = EXCLUDED.updated_at, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE fulfillments.updated_at < EXCLUDED.updated_at"
        ),
        {
            "order_id": payload.get("order_id", ""),
            "patient_id": payload.get("patient_id", ""),
            "status": payload.get("status", ""),
            "shipping_option": payload.get("shipping_option", ""),
            "tracking_numbers": json.dumps(payload.get("tracking_numbers", [])),
            "order_items": json.dumps(payload.get("order_items", [])),
            "devices": json.dumps(payload.get("devices", [])),
            "created_at": now,
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )

    log.info(
        "fulfillment_projected",
        order_id=payload.get("order_id"),
        status=payload.get("status"),
    )


async def handle_return_updated(event_data: dict, session) -> None:
    """Project return.updated -- upsert returns row by return_id."""
    payload = event_data.get("payload", {})
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO returns "
            "  (return_id, patient_id, device_id, order_id, status, reason, "
            "   raw_payload, created_at, updated_at, last_event_id) "
            "VALUES "
            "  (:return_id, :patient_id, :device_id, :order_id, :status, :reason, "
            "   :raw_payload::jsonb, :created_at, :updated_at, :event_id) "
            "ON CONFLICT (return_id) DO UPDATE SET "
            "  status = EXCLUDED.status, "
            "  reason = EXCLUDED.reason, "
            "  raw_payload = EXCLUDED.raw_payload, "
            "  updated_at = EXCLUDED.updated_at, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE returns.updated_at < EXCLUDED.updated_at"
        ),
        {
            "return_id": payload.get("return_id", ""),
            "patient_id": payload.get("patient_id", ""),
            "device_id": payload.get("device_id", ""),
            "order_id": payload.get("order_id", ""),
            "status": payload.get("status", ""),
            "reason": payload.get("reason", ""),
            "raw_payload": json.dumps(payload.get("raw_payload", {})),
            "created_at": now,
            "updated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )

    log.info(
        "return_projected",
        return_id=payload.get("return_id"),
        status=payload.get("status"),
    )


async def handle_device_associated(event_data: dict, session) -> None:
    """Project device.associated -- upsert device_associations with status='active'."""
    payload = event_data.get("payload", {})
    now = datetime.now(tz=UTC)

    await session.execute(
        sa.text(
            "INSERT INTO device_associations "
            "  (patient_id, device_id, device_name, status, associated_at, last_event_id) "
            "VALUES "
            "  (:patient_id, :device_id, :device_name, 'active', :associated_at, :event_id) "
            "ON CONFLICT (patient_id, device_id) DO UPDATE SET "
            "  device_name = EXCLUDED.device_name, "
            "  status = 'active', "
            "  associated_at = EXCLUDED.associated_at, "
            "  removed_at = NULL, "
            "  last_event_id = EXCLUDED.last_event_id "
            "WHERE device_associations.last_event_id IS DISTINCT FROM EXCLUDED.last_event_id"
        ),
        {
            "patient_id": payload.get("patient_id", ""),
            "device_id": payload.get("device_id", ""),
            "device_name": payload.get("device_name", ""),
            "associated_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )

    log.info(
        "device_associated_projected",
        patient_id=payload.get("patient_id"),
        device_id=payload.get("device_id"),
    )


async def handle_device_disassociated(event_data: dict, session) -> None:
    """Project device.disassociated -- set status='removed' and removed_at."""
    payload = event_data.get("payload", {})
    now = datetime.now(tz=UTC)

    result = await session.execute(
        sa.text(
            "UPDATE device_associations SET "
            "  status = 'removed', "
            "  removed_at = :removed_at, "
            "  last_event_id = :event_id "
            "WHERE patient_id = :patient_id AND device_id = :device_id AND status = 'active'"
        ),
        {
            "patient_id": payload.get("patient_id", ""),
            "device_id": payload.get("device_id", ""),
            "removed_at": now,
            "event_id": event_data.get("event_id", ""),
        },
    )

    if result.rowcount == 0:
        log.warning(
            "device_disassociation_noop",
            patient_id=payload.get("patient_id"),
            device_id=payload.get("device_id"),
            reason="no active association found",
        )
    else:
        log.info(
            "device_disassociated_projected",
            patient_id=payload.get("patient_id"),
            device_id=payload.get("device_id"),
        )
