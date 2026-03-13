"""Impilo payload normalizer — converts raw Impilo webhook dict to canonical Ocean events."""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

import structlog
from ocean_events.base import BaseEvent, _PHI_FIELD_NAMES

log = structlog.get_logger()

# Impilo event type prefix -> (ocean_event_type, ocean_topic, entity_type)
EVENT_MAP: dict[str, tuple[str, str, str]] = {
    "reading":     ("signal.received",       "ocean.signals",    "signal"),
    "patient":     ("patient.enrolled",       "ocean.signals",    "patient"),
    "device":      ("signal.missing",         "ocean.signals",    "signal"),
    "order":       ("order.created",          "ocean.logistics",  "logistics"),
    "kit":         ("kit.updated",            "ocean.logistics",  "logistics"),
    "procurement": ("procurement.requested",  "ocean.logistics",  "logistics"),
    "return":      ("return.updated",         "ocean.logistics",  "return"),
}

# Subtype-level overrides — checked before prefix-level EVENT_MAP.
# Full type string -> (ocean_event_type, ocean_topic, entity_type)
SUBTYPE_MAP: dict[str, tuple[str, str, str]] = {
    "order.statusFull":          ("fulfillment.updated",    "ocean.logistics", "fulfillment"),
    "return.statusFull":         ("return.updated",         "ocean.logistics", "return"),
    "device.associationCreated": (
        "device.associated", "ocean.logistics", "device_association",
    ),
    "device.associationRemoved": (
        "device.disassociated", "ocean.logistics", "device_association",
    ),
}

# For device events, only inactive/lost map to signal.missing.
DEVICE_OFFLINE_STATUSES = {"inactive", "lost"}

# Impilo sends PHI in camelCase (firstName, lastName, etc.).
# Extend the shared denylist with camelCase variants for raw input checking.
_CAMEL_CASE_PHI: frozenset[str] = frozenset({
    "firstName", "lastName", "fullName", "dateOfBirth",
    "medicalRecordNumber", "socialSecurityNumber",
    "streetAddress", "zipCode", "postalCode",
    "phoneNumber", "cellPhone", "homePhone",
    "emailAddress", "diagnosisCode", "icdCode",
    "clinicalNote", "chartNote", "glucoseValue",
    "bloodPressure", "weightKg",
})

_ALL_PHI_KEYS: frozenset[str] = _PHI_FIELD_NAMES | _CAMEL_CASE_PHI


def _check_no_phi_keys(d: dict) -> None:
    """Recursively check all keys in dict against PHI denylist. Raises ValueError on match."""
    matched: set[str] = set()
    _collect_phi_keys(d, matched)
    if matched:
        raise ValueError(
            f"PHI field(s) detected in payload: {sorted(matched)!r}. "
            "PHI must not enter published events."
        )


def _collect_phi_keys(d: dict, matched: set[str]) -> None:
    """Walk dict recursively, collecting any keys that match PHI denylist."""
    for key, value in d.items():
        if key in _ALL_PHI_KEYS:
            matched.add(key)
        if isinstance(value, dict):
            _collect_phi_keys(value, matched)


def _extract_patient_id(raw: dict, prefix: str) -> str:
    """Extract and SHA-256 hash the patient ID from raw Impilo payload.

    For readings and device events: patient ID at raw["patient"]["id"].
    For patient events: patient ID at raw["id"].
    For logistics: may not exist — returns "unknown" hash.
    """
    raw_id: int | str | None = None

    if prefix in ("reading", "device"):
        patient_obj = raw.get("patient")
        if isinstance(patient_obj, dict):
            raw_id = patient_obj.get("id")
    elif prefix == "patient":
        raw_id = raw.get("id")
    else:
        # Logistics — patient may not be present
        patient_obj = raw.get("patient")
        if isinstance(patient_obj, dict):
            raw_id = patient_obj.get("id")

    if raw_id is None:
        raw_id = "unknown"

    return hashlib.sha256(f"impilo:patient:{raw_id}".encode()).hexdigest()


def _derive_event_id(entity_type: str, payload_id: str | int) -> uuid.UUID:
    """Deterministic event_id via SHA-256 — same Impilo entity always maps to same UUID."""
    digest = hashlib.sha256(f"impilo:{entity_type}:{payload_id}".encode()).digest()
    return uuid.UUID(bytes=digest[:16])


def _extract_signal_type(event_type: str) -> str:
    """Extract signal subtype from Impilo event type string.

    "reading.weight" -> "weight"
    "reading.blood_pressure" -> "blood_pressure"
    "device.inactive" -> "device_offline"
    """
    parts = event_type.split(".", 1)
    prefix = parts[0]
    subtype = parts[1] if len(parts) > 1 else prefix

    if prefix == "device":
        return "device_offline"
    return subtype


def normalize_impilo_payload(raw: dict) -> tuple[BaseEvent, str]:
    """Normalize a raw Impilo webhook dict into a canonical (BaseEvent, topic) tuple.

    Steps:
    1. Parse event type prefix from raw["type"]
    2. Look up Ocean event mapping
    3. For device events, validate offline status
    4. Check raw input for PHI keys (defense in depth)
    5. Extract needed fields, build clean payload
    6. Verify built payload has no PHI keys
    7. Construct BaseEvent
    8. Return (event, topic)

    Raises:
        ValueError: unknown event type, PHI detected, or unmapped device event
    """
    event_type_str: str = raw["type"]
    prefix = event_type_str.split(".")[0]

    # Check subtype-level overrides first (exact match on full type string)
    is_subtype = event_type_str in SUBTYPE_MAP
    if is_subtype:
        ocean_event_type, topic, entity_type = SUBTYPE_MAP[event_type_str]
    elif prefix in EVENT_MAP:
        ocean_event_type, topic, entity_type = EVENT_MAP[prefix]
    else:
        raise ValueError(
            f"Unknown Impilo event type prefix '{prefix}' from '{event_type_str}'. "
            f"Known prefixes: {sorted(EVENT_MAP.keys())}"
        )

    # For device events using prefix-level mapping, only inactive/lost map to signal.missing
    if prefix == "device" and not is_subtype:
        subtype = event_type_str.split(".", 1)[1] if "." in event_type_str else ""
        status = raw.get("status", subtype)
        if status not in DEVICE_OFFLINE_STATUSES and subtype not in DEVICE_OFFLINE_STATUSES:
            raise ValueError(
                f"Device event '{event_type_str}' (status={status}) not mapped "
                "-- only inactive/lost produce signal.missing"
            )

    # Check raw input for PHI keys (catches camelCase Impilo PHI)
    _check_no_phi_keys(raw)

    payload_id = raw["id"]
    event_id = _derive_event_id(entity_type, payload_id)
    hashed_patient_id = _extract_patient_id(raw, prefix)

    # Parse timestamp
    created_at_str = raw.get("createdAt")
    if created_at_str:
        ts = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    else:
        ts = datetime.now(tz=timezone.utc)

    # Build clean payload based on event category
    if ocean_event_type == "fulfillment.updated":
        payload = {
            "order_id": str(raw["id"]),
            "patient_id": hashed_patient_id,
            "status": raw.get("status", ""),
            "shipping_option": raw.get("shippingOption", ""),
            "tracking_numbers": raw.get("trackingNumbers", []),
            "order_items": raw.get("orderItems", []),
            "devices": raw.get("devices", []),
        }
    elif ocean_event_type == "return.updated":
        payload = {
            "return_id": str(raw["id"]),
            "patient_id": hashed_patient_id,
            "device_id": str(raw.get("device", {}).get("id", "")),
            "order_id": str(raw.get("order", {}).get("id", "")),
            "status": raw.get("status", ""),
            "reason": raw.get("reason", ""),
            "raw_payload": raw,
        }
    elif ocean_event_type == "device.associated":
        payload = {
            "patient_id": hashed_patient_id,
            "device_id": str(raw.get("device", {}).get("id", "")),
            "device_name": raw.get("device", {}).get("name", ""),
            "order_id": str(raw.get("order", {}).get("id", "")) if raw.get("order") else None,
        }
    elif ocean_event_type == "device.disassociated":
        payload = {
            "patient_id": hashed_patient_id,
            "device_id": str(raw.get("device", {}).get("id", "")),
            "device_name": raw.get("device", {}).get("name", ""),
        }
    elif prefix == "reading":
        payload = {
            "signal_type": _extract_signal_type(event_type_str),
            "patient_id": hashed_patient_id,
            "value": raw.get("value") or raw.get("systolic"),
            "unit": raw.get("unit", ""),
            "source_reading_type": event_type_str,
            "reading_type": event_type_str,
        }
    elif prefix == "patient":
        payload = {
            "patient_id": hashed_patient_id,
            "enrollment_status": "enrolled",
            "source_patient_type": event_type_str,
        }
    elif prefix == "device":
        payload = {
            "signal_type": "device_offline",
            "patient_id": hashed_patient_id,
            "device_id": str(raw.get("id", "")),
            "source_device_status": raw.get("status", ""),
        }
    else:
        # Logistics (order, kit, procurement)
        payload = {
            "logistics_type": event_type_str,
            "entity_id": str(payload_id),
            "patient_id": hashed_patient_id,
        }

    # Safety net: verify built payload has no PHI keys
    _check_no_phi_keys(payload)

    event = BaseEvent(
        event_id=event_id,
        event_type=ocean_event_type,
        schema_version="1.0.0",
        timestamp=ts,
        source_system="impilo",
        entity_type=entity_type,
        entity_id=str(payload_id),
        correlation_id=str(event_id),
        actor_id=None,
        payload=payload,
    )

    log.debug(
        "impilo_event_normalized",
        event_type=ocean_event_type,
        topic=topic,
        entity_id=str(payload_id),
    )

    return event, topic
