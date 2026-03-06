"""Tests for BaseEvent PHI guard and envelope validation."""
from __future__ import annotations

import importlib
import sys
import textwrap
import uuid
from datetime import datetime, timezone

import pytest


def make_valid_event_class():
    """Return a valid BaseEvent subclass with no PHI fields."""
    from ocean_events import BaseEvent

    class SomeEvent(BaseEvent):
        event_count: int = 0

    return SomeEvent


def make_valid_event(**overrides):
    """Construct a valid SomeEvent instance with all required fields."""
    SomeEvent = make_valid_event_class()
    defaults = dict(
        event_id=uuid.uuid4(),
        event_type="alert.created",
        schema_version="1.0.0",
        timestamp=datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc),
        source_system="ocean",
        entity_type="alert",
        entity_id="alert-001",
        correlation_id="corr-001",
        actor_id="system",
        payload={},
    )
    defaults.update(overrides)
    return SomeEvent(**defaults)


# ---------------------------------------------------------------------------
# PHI guard — field-level (import-time)
# ---------------------------------------------------------------------------


def test_phi_field_in_subclass_raises_at_import_time():
    """Defining a BaseEvent subclass with patient_name raises TypeError at class definition."""
    from ocean_events import BaseEvent

    with pytest.raises(TypeError, match="patient_name"):

        class BadEvent(BaseEvent):
            patient_name: str


def test_phi_field_dob_raises():
    """Defining a BaseEvent subclass with dob field raises TypeError."""
    from ocean_events import BaseEvent

    with pytest.raises(TypeError, match="dob"):

        class BadEvent(BaseEvent):
            dob: str


def test_phi_field_mrn_raises():
    """Defining a BaseEvent subclass with mrn field raises TypeError."""
    from ocean_events import BaseEvent

    with pytest.raises(TypeError, match="mrn"):

        class BadEvent(BaseEvent):
            mrn: str


def test_phi_field_email_raises():
    """Defining a BaseEvent subclass with email field raises TypeError."""
    from ocean_events import BaseEvent

    with pytest.raises(TypeError, match="email"):

        class BadEvent(BaseEvent):
            email: str


# ---------------------------------------------------------------------------
# PHI guard — payload-level (instance-time)
# ---------------------------------------------------------------------------


def test_phi_payload_key_raises():
    """Constructing an event with PHI key in payload raises ValueError."""
    with pytest.raises(ValueError, match="PHI"):
        make_valid_event(payload={"patient_name": "Alice Smith"})


def test_phi_payload_key_dob_raises():
    """Constructing an event with dob key in payload raises ValueError."""
    with pytest.raises(ValueError, match="PHI"):
        make_valid_event(payload={"dob": "1980-01-01"})


# ---------------------------------------------------------------------------
# Valid event construction
# ---------------------------------------------------------------------------


def test_valid_event_constructs():
    """A valid BaseEvent subclass with clean fields constructs successfully."""
    event = make_valid_event()
    assert event.event_type == "alert.created"
    assert event.entity_id == "alert-001"
    assert event.schema_version == "1.0.0"
    assert event.source_system == "ocean"


def test_valid_event_with_clean_payload():
    """An event with a non-PHI payload constructs successfully."""
    event = make_valid_event(payload={"alert_type": "glucose_missing", "severity": "urgent"})
    assert event.payload["alert_type"] == "glucose_missing"


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_event_is_frozen():
    """Attempting to set a field on a constructed event raises an error (frozen model)."""
    event = make_valid_event()
    with pytest.raises(Exception):  # pydantic raises ValidationError for frozen models
        event.entity_id = "new-id"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_event_roundtrip_json():
    """Event serializes to JSON and back with all fields intact."""
    event = make_valid_event()
    json_str = event.model_dump_json()
    restored = make_valid_event_class().model_validate_json(json_str)
    assert restored.event_id == event.event_id
    assert restored.event_type == event.event_type
    assert restored.entity_id == event.entity_id
    assert restored.correlation_id == event.correlation_id
    assert restored.payload == event.payload
