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


def _event_time(event_data: dict) -> datetime:
    """The envelope timestamp, fixed when the event was produced.

    A sequence guard must compare event time. Every other timestamp on these rows
    is assigned at processing time, which under unordered delivery encodes arrival
    order instead of event order. The envelope always carries this field, so a
    missing or unparseable value is a malformed event: raise and let the consumer
    redeliver rather than silently guard on nothing.
    """
    return _parse_ts(event_data["timestamp"])


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
    """Project device.associated -- upsert device_associations with status='active'.

    Guarded on ``last_event_at``. The predicate this replaced compared event ids,
    which suppresses a duplicate but lets an association that was already
    superseded by a disassociation resurrect the device when it arrives late.
    Comparing event time subsumes the dedup it replaced: a redelivered event has
    the same timestamp, so it too fails the strict comparison.
    """
    payload = event_data.get("payload", {})
    now = datetime.now(tz=UTC)

    result = await session.execute(
        sa.text(
            "INSERT INTO device_associations "
            "  (patient_id, device_id, device_name, status, associated_at, "
            "   last_event_id, last_event_at) "
            "VALUES "
            "  (:patient_id, :device_id, :device_name, 'active', :associated_at, "
            "   :event_id, :event_at) "
            "ON CONFLICT (patient_id, device_id) DO UPDATE SET "
            "  device_name = EXCLUDED.device_name, "
            "  status = 'active', "
            "  associated_at = EXCLUDED.associated_at, "
            "  removed_at = NULL, "
            "  last_event_id = EXCLUDED.last_event_id, "
            "  last_event_at = EXCLUDED.last_event_at "
            "WHERE device_associations.last_event_at IS NULL "
            "   OR device_associations.last_event_at < EXCLUDED.last_event_at"
        ),
        {
            "patient_id": payload.get("patient_id", ""),
            "device_id": payload.get("device_id", ""),
            "device_name": payload.get("device_name", ""),
            "associated_at": now,
            "event_id": event_data.get("event_id", ""),
            "event_at": _event_time(event_data),
        },
    )

    if result.rowcount == 0:
        log.info(
            "device_association_stale",
            patient_id=payload.get("patient_id"),
            device_id=payload.get("device_id"),
            reason="a later event already set this association's state",
        )
    else:
        log.info(
            "device_associated_projected",
            patient_id=payload.get("patient_id"),
            device_id=payload.get("device_id"),
        )


async def handle_device_disassociated(event_data: dict, session) -> None:
    """Project device.disassociated -- record status='removed' and removed_at.

    An upsert rather than an UPDATE, and guarded on ``last_event_at`` rather than
    on ``status = 'active'``. Both changes exist for the same reason: when this
    event is delivered before the association it removes, the old UPDATE matched
    nothing and the older association then arrived and created an active row, so
    the entity converged on the wrong terminal state. Writing the removed row here
    gives the stale association something to lose against.
    """
    payload = event_data.get("payload", {})
    now = datetime.now(tz=UTC)

    result = await session.execute(
        sa.text(
            "INSERT INTO device_associations "
            "  (patient_id, device_id, device_name, status, associated_at, "
            "   removed_at, last_event_id, last_event_at) "
            "VALUES "
            "  (:patient_id, :device_id, :device_name, 'removed', :now, "
            "   :removed_at, :event_id, :event_at) "
            "ON CONFLICT (patient_id, device_id) DO UPDATE SET "
            "  status = 'removed', "
            "  removed_at = EXCLUDED.removed_at, "
            "  last_event_id = EXCLUDED.last_event_id, "
            "  last_event_at = EXCLUDED.last_event_at "
            "WHERE device_associations.last_event_at IS NULL "
            "   OR device_associations.last_event_at < EXCLUDED.last_event_at"
        ),
        {
            "patient_id": payload.get("patient_id", ""),
            "device_id": payload.get("device_id", ""),
            "device_name": payload.get("device_name", ""),
            # A tombstone written before its association has no observed
            # association time; the column is NOT NULL, so it takes the clock.
            "now": now,
            "removed_at": now,
            "event_id": event_data.get("event_id", ""),
            "event_at": _event_time(event_data),
        },
    )

    if result.rowcount == 0:
        log.info(
            "device_disassociation_stale",
            patient_id=payload.get("patient_id"),
            device_id=payload.get("device_id"),
            reason="a later event already set this association's state",
        )
    else:
        log.info(
            "device_disassociated_projected",
            patient_id=payload.get("patient_id"),
            device_id=payload.get("device_id"),
        )
