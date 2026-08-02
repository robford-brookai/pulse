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


def make_order_status_full_payload(
    order_id: int = 1001,
    patient_id: int = 123,
) -> dict:
    return {
        "type": "order.statusFull",
        "id": order_id,
        "patient": {"id": patient_id},
        "status": "shipped",
        "shippingOption": "standard",
        "trackingNumbers": ["1Z999AA10123456784"],
        "orderItems": [{"sku": "BP-100", "qty": 1}],
        "devices": [{"id": 5001, "name": "BP Monitor"}],
        "createdAt": "2026-03-06T10:00:00Z",
    }


def make_return_status_full_payload(
    return_id: int = 2001,
    patient_id: int = 123,
) -> dict:
    return {
        "type": "return.statusFull",
        "id": return_id,
        "patient": {"id": patient_id},
        "device": {"id": 789, "name": "BP Monitor"},
        "order": {"id": 1001},
        "status": "received",
        "reason": "defective",
        "createdAt": "2026-03-06T10:00:00Z",
    }


def make_device_association_created_payload(
    patient_id: int = 123,
) -> dict:
    return {
        "type": "device.associationCreated",
        "id": 3001,
        "patient": {"id": patient_id},
        "device": {"id": 789, "name": "BP Monitor"},
        "order": {"id": 1001},
        "createdAt": "2026-03-06T10:00:00Z",
    }


def make_device_association_removed_payload(
    patient_id: int = 123,
) -> dict:
    return {
        "type": "device.associationRemoved",
        "id": 3002,
        "patient": {"id": patient_id},
        "device": {"id": 789, "name": "BP Monitor"},
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
        expected_hash = hashlib.sha256(b"impilo:patient:123").hexdigest()
        assert event.payload["patient_id"] == expected_hash

    def test_deterministic_event_id(self) -> None:
        e1, _ = normalize_impilo_payload(make_reading_payload())
        e2, _ = normalize_impilo_payload(make_reading_payload())
        assert e1.event_id == e2.event_id


class TestFulfillmentEvents:
    """order.statusFull -> fulfillment.updated on ocean.logistics."""

    def test_order_status_full_produces_fulfillment_updated(self) -> None:
        raw = make_order_status_full_payload()
        event, topic = normalize_impilo_payload(raw)
        assert event.event_type == "fulfillment.updated"
        assert event.entity_type == "fulfillment"
        assert topic == "ocean.logistics"

    def test_order_status_full_payload_fields(self) -> None:
        raw = make_order_status_full_payload()
        event, _ = normalize_impilo_payload(raw)
        assert event.payload["order_id"] == "1001"
        assert event.payload["status"] == "shipped"
        assert event.payload["shipping_option"] == "standard"
        assert event.payload["tracking_numbers"] == ["1Z999AA10123456784"]
        assert event.payload["order_items"] == [{"sku": "BP-100", "qty": 1}]
        assert event.payload["devices"] == [{"id": 5001, "name": "BP Monitor"}]
        # patient_id should be hashed
        expected_hash = hashlib.sha256(b"impilo:patient:123").hexdigest()
        assert event.payload["patient_id"] == expected_hash


class TestReturnEvents:
    """return.statusFull -> return.updated on ocean.logistics."""

    def test_return_status_full_produces_return_updated(self) -> None:
        raw = make_return_status_full_payload()
        event, topic = normalize_impilo_payload(raw)
        assert event.event_type == "return.updated"
        assert event.entity_type == "return"
        assert topic == "ocean.logistics"

    def test_return_status_full_payload_fields(self) -> None:
        raw = make_return_status_full_payload()
        event, _ = normalize_impilo_payload(raw)
        assert event.payload["return_id"] == "2001"
        assert event.payload["status"] == "received"
        assert event.payload["reason"] == "defective"
        assert event.payload["device_id"] == "789"
        assert event.payload["order_id"] == "1001"
        assert "raw_payload" in event.payload


class TestDeviceAssociationEvents:
    """device.associationCreated/Removed -> device.associated/disassociated."""

    def test_device_association_created_produces_device_associated(self) -> None:
        raw = make_device_association_created_payload()
        event, topic = normalize_impilo_payload(raw)
        assert event.event_type == "device.associated"
        assert event.entity_type == "device_association"
        assert topic == "ocean.logistics"

    def test_device_association_created_payload_fields(self) -> None:
        raw = make_device_association_created_payload()
        event, _ = normalize_impilo_payload(raw)
        assert event.payload["device_id"] == "789"
        assert event.payload["device_name"] == "BP Monitor"
        assert event.payload["order_id"] == "1001"

    def test_device_association_removed_produces_device_disassociated(self) -> None:
        raw = make_device_association_removed_payload()
        event, topic = normalize_impilo_payload(raw)
        assert event.event_type == "device.disassociated"
        assert event.entity_type == "device_association"
        assert topic == "ocean.logistics"

    def test_device_association_removed_has_no_order_id(self) -> None:
        raw = make_device_association_removed_payload()
        event, _ = normalize_impilo_payload(raw)
        assert event.payload["device_id"] == "789"
        assert event.payload["device_name"] == "BP Monitor"
        assert event.payload.get("order_id") is None


class TestReadingPassthrough:
    """reading.* events should include reading_type field."""

    def test_reading_has_reading_type_field(self) -> None:
        event, _ = normalize_impilo_payload(make_reading_payload("weight"))
        assert event.payload["reading_type"] == "reading.weight"


class TestEdgeCases:
    def test_unknown_event_type_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_impilo_payload({"type": "unknown.thing", "id": 1, "createdAt": "2026-03-06T10:00:00Z"})
