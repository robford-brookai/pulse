"""POCAR payload normalizer — converts raw webhook dict to canonical OceanEvent."""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC

import structlog
from ocean_events.base import BaseEvent

from src.schema.pocar_webhook import POCARWebhookPayload

log = structlog.get_logger()

# Explicit PHI field denylist — checked against raw dict keys at normalizer boundary.
# Independent of BaseEvent's payload-key check (defence in depth).
PHI_FIELD_DENYLIST: frozenset[str] = frozenset({
    "patient_name",
    "first_name",
    "last_name",
    "dob",
    "date_of_birth",
    "mrn",
    "ssn",
    "email",
    "phone",
    "address",
})


def _check_no_phi_keys(raw: dict) -> None:
    """Raise ValueError if any raw dict key matches the PHI denylist."""
    matched_keys = PHI_FIELD_DENYLIST.intersection(raw.keys())
    if matched_keys:
        raise ValueError(
            f"PHI field(s) detected in raw payload: {sorted(matched_keys)!r}. "
            "PHI must not enter the normalizer."
        )


def _extract_patient_id(raw: dict) -> str:
    """Return the patient identifier from the raw payload.

    Wrapped here so if POCAR later confirms this is an MRN, SHA-256 hashing
    is added in exactly one place.
    """
    return raw["patient_id"]


def normalize_pocar_payload(raw: dict) -> BaseEvent:
    """Normalize a raw POCAR webhook dict into a canonical BaseEvent.

    Steps:
    1. PHI key denylist check (independent of BaseEvent construction)
    2. Pydantic validation against POCARWebhookPayload
    3. Deterministic event_id via SHA-256("pocar:" + alert_id) → UUID
    4. Construct and return BaseEvent

    Raises:
        ValueError: if PHI keys present in raw dict
        ValidationError: if payload fails schema validation
    """
    _check_no_phi_keys(raw)

    validated = POCARWebhookPayload.model_validate(raw)

    # Deterministic event_id — same alert_id always yields same UUID (idempotency key)
    digest = hashlib.sha256(f"pocar:{validated.alert_id}".encode()).digest()
    event_id = uuid.UUID(bytes=digest[:16])

    # Ensure triggered_at is timezone-aware (UTC)
    triggered_at = validated.triggered_at
    if triggered_at.tzinfo is None:
        triggered_at = triggered_at.replace(tzinfo=UTC)

    return BaseEvent(
        event_id=event_id,
        event_type="alert.created",
        schema_version="1.0.0",
        timestamp=triggered_at,
        source_system="pocar",
        entity_type="alert",
        entity_id=validated.alert_id,
        correlation_id=str(event_id),
        actor_id=None,
        payload={
            "alert_type": validated.alert_type,
            "severity": validated.severity,
            "patient_id": _extract_patient_id(raw),
            "clinic_id": validated.clinic_id,
            "signal_type": validated.signal_type,
            "signal_value": validated.signal_value,
        },
    )
