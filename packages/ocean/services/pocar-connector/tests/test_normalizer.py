"""Tests for POCAR normalizer — PHI denylist, idempotency, field mapping."""
from __future__ import annotations

import pytest


def _make_valid_raw(**overrides) -> dict:
    base = {
        "alert_id": "alert-001",
        "patient_id": "pt-abc123",
        "alert_type": "glucose_missing",
        "severity": "urgent",
        "clinic_id": "clinic-1",
        "triggered_at": "2026-03-05T10:00:00Z",
    }
    base.update(overrides)
    return base


def test_normalize_produces_alert_created_event():
    """normalize_pocar_payload returns event_type='alert.created', source_system='pocar'."""
    from src.normalizer import normalize_pocar_payload

    event = normalize_pocar_payload(_make_valid_raw())
    assert event.event_type == "alert.created"
    assert event.source_system == "pocar"
    assert event.entity_type == "alert"
    assert event.entity_id == "alert-001"


def test_normalize_deterministic_event_id():
    """Same alert_id always produces the same event_id."""
    from src.normalizer import normalize_pocar_payload

    raw = _make_valid_raw()
    event1 = normalize_pocar_payload(raw)
    event2 = normalize_pocar_payload(raw)
    assert event1.event_id == event2.event_id


def test_normalize_phi_in_payload_raises():
    """PHI key in raw dict raises ValueError — denylist check is independent of BaseEvent."""
    from src.normalizer import normalize_pocar_payload

    raw = _make_valid_raw()
    raw["patient_name"] = "John Doe"  # PHI key — must be caught by denylist
    with pytest.raises(ValueError, match="PHI field"):
        normalize_pocar_payload(raw)


def test_extract_patient_id_passthrough():
    """_extract_patient_id returns patient_id directly (opaque ID passthrough)."""
    from src.normalizer import _extract_patient_id

    assert _extract_patient_id({"patient_id": "abc"}) == "abc"
