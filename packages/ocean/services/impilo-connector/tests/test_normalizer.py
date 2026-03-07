"""Tests for the Impilo payload normalizer."""
from __future__ import annotations

import hashlib

import pytest

from src.normalizer import normalize_impilo_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_reading_payload(
    reading_type: str = "weight",
    patient_id: int = 123,
    reading_id: int = 456,
) -> dict:
    return {
        "type": f"reading.{reading_type}",
        "id": reading_id,
        "patient": {"id": patient_id},
        "value": 185.5,
        "unit": "lbs",
        "createdAt": "2026-03-06T10:00:00Z",
    }


def make_patient_payload(
    patient_id: int = 123,
    event_type: str = "patient.created",
) -> dict:
    return {
        "type": event_type,
        "id": patient_id,
        "createdAt": "2026-03-06T10:00:00Z",
    }


def make_device_payload(
    device_id: int = 789,
    patient_id: int = 123,
    status: str = "inactive",
) -> dict:
    return {
        "type": f"device.{status}",
        "id": device_id,
        "status": status,
        "patient": {"id": patient_id},
        "createdAt": "2026-03-06T10:00:00Z",
    }


def make_order_payload(order_id: int = 999) -> dict:
    return {
        "type": "order.created",
        "id": order_id,
        "createdAt": "2026-03-06T10:00:00Z",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReadingEvents:
    def test_reading_weight_produces_signal_received(self) -> None:
        event, topic = normalize_impilo_payload(make_reading_payload("weight"))
        assert event.event_type == "signal.received"
        assert event.source_system == "impilo"
        assert event.entity_type == "signal"
        assert event.payload["signal_type"] == "weight"
        assert topic == "ocean.signals"

    def test_reading_blood_pressure_preserves_subtype(self) -> None:
        event, topic = normalize_impilo_payload(make_reading_payload("blood_pressure"))
        assert event.payload["signal_type"] == "blood_pressure"
        assert topic == "ocean.signals"


class TestPatientEvents:
    def test_patient_created_produces_patient_enrolled(self) -> None:
        event, topic = normalize_impilo_payload(make_patient_payload())
        assert event.event_type == "patient.enrolled"
        assert event.entity_type == "patient"
        assert topic == "ocean.signals"


class TestDeviceEvents:
    def test_device_inactive_produces_signal_missing(self) -> None:
        event, topic = normalize_impilo_payload(make_device_payload(status="inactive"))
        assert event.event_type == "signal.missing"
        assert event.payload["signal_type"] == "device_offline"
        assert topic == "ocean.signals"


class TestLogisticsEvents:
    def test_order_created_maps_to_logistics(self) -> None:
        event, topic = normalize_impilo_payload(make_order_payload())
        assert event.event_type == "order.created"
        assert topic == "ocean.logistics"


class TestPHIProtection:
    def test_phi_stripped_from_payload(self) -> None:
        """PHI keys in the raw Impilo dict must trigger ValueError."""
        raw = make_reading_payload()
        raw["firstName"] = "John"
        raw["lastName"] = "Doe"
        raw["dob"] = "1990-01-01"
        with pytest.raises(ValueError, match="PHI"):
            normalize_impilo_payload(raw)

    def test_nested_phi_also_caught(self) -> None:
        """PHI inside nested dicts (e.g. patient sub-object) must also be caught."""
        raw = make_reading_payload()
        raw["patient"]["firstName"] = "John"
        with pytest.raises(ValueError, match="PHI"):
            normalize_impilo_payload(raw)


class TestIdentityHashing:
    def test_patient_id_is_sha256_hash(self) -> None:
        event, _ = normalize_impilo_payload(make_reading_payload(patient_id=123))
        expected_hash = hashlib.sha256("impilo:patient:123".encode()).hexdigest()
        assert event.payload["patient_id"] == expected_hash

    def test_deterministic_event_id(self) -> None:
        e1, _ = normalize_impilo_payload(make_reading_payload())
        e2, _ = normalize_impilo_payload(make_reading_payload())
        assert e1.event_id == e2.event_id


class TestEdgeCases:
    def test_unknown_event_type_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_impilo_payload(
                {"type": "unknown.thing", "id": 1, "createdAt": "2026-03-06T10:00:00Z"}
            )
