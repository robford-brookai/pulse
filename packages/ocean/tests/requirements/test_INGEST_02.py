"""INGEST-02: All 4 ZCC call lifecycle events normalised and published.

Requirement: The ZCC connector normalises all four Zoom Contact Center webhook
event types into canonical Ocean event envelopes and publishes them to
ocean.interactions. The four event types are:
  - contact_center.engagement_started  → call.started
  - contact_center.engagement_answered → call.connected
  - contact_center.engagement_ended    → call.completed
  - contact_center.engagement_missed   → call.missed
"""

from __future__ import annotations

import pytest
from utils import setup_service

setup_service("zcc-connector")

from src.normalizer import ZCC_TO_OCEAN_EVENT_TYPE, normalize_zcc_event


def _zcc_payload(zcc_event: str, engagement_id: str = "eng-001", task_id: str = "task-abc") -> dict:
    return {
        "event": zcc_event,
        "payload": {
            "object": {
                "engagement_id": engagement_id,
                "id": engagement_id,
                "assigned_to": {"id": "agent-1"},
                "duration": 180,
                "disposition_name": "resolved",
                "patient_id": "pt-001",
                "task_id": task_id,
            }
        },
    }


_ZCC_EVENT_MAPPINGS = [
    ("contact_center.engagement_started", "call.started"),
    ("contact_center.engagement_answered", "call.connected"),
    ("contact_center.engagement_ended", "call.completed"),
    ("contact_center.engagement_missed", "call.missed"),
]


@pytest.mark.parametrize("zcc_event,expected_ocean_event", _ZCC_EVENT_MAPPINGS)
def test_all_four_zcc_events_are_mapped(zcc_event: str, expected_ocean_event: str):
    """Each ZCC event type maps to its canonical Ocean event type."""
    result = normalize_zcc_event(_zcc_payload(zcc_event))

    assert result is not None, f"normalize_zcc_event returned None for '{zcc_event}'"
    assert result["event_type"] == expected_ocean_event, (
        f"Expected '{expected_ocean_event}', got '{result['event_type']}'"
    )


def test_all_four_mappings_in_zcc_to_ocean_table():
    """ZCC_TO_OCEAN_EVENT_TYPE dict contains exactly the 4 required mappings."""
    expected_zcc_events = {
        "contact_center.engagement_started",
        "contact_center.engagement_answered",
        "contact_center.engagement_ended",
        "contact_center.engagement_missed",
    }
    assert expected_zcc_events == set(ZCC_TO_OCEAN_EVENT_TYPE.keys()), (
        f"Mapping table mismatch. Found: {set(ZCC_TO_OCEAN_EVENT_TYPE.keys())}"
    )

    expected_ocean_events = {"call.started", "call.connected", "call.completed", "call.missed"}
    assert expected_ocean_events == set(ZCC_TO_OCEAN_EVENT_TYPE.values())


@pytest.mark.parametrize("zcc_event,_", _ZCC_EVENT_MAPPINGS)
def test_normalized_event_has_canonical_envelope(zcc_event: str, _):
    """Normalized event includes all Ocean canonical envelope fields."""
    result = normalize_zcc_event(_zcc_payload(zcc_event))

    assert result is not None
    for field in ("event_id", "event_type", "timestamp", "source_system", "entity_type", "entity_id", "payload"):
        assert field in result, f"Canonical field '{field}' missing from normalized '{zcc_event}'"

    assert result["source_system"] == "zcc"
    assert result["entity_type"] == "interaction"


@pytest.mark.parametrize("zcc_event,_", _ZCC_EVENT_MAPPINGS)
def test_normalized_event_preserves_task_id(zcc_event: str, _):
    """task_id from ZCC payload is preserved in normalized event for ZCC-02 correlation."""
    result = normalize_zcc_event(_zcc_payload(zcc_event, task_id="task-corr-999"))

    assert result is not None
    assert result["payload"].get("task_id") == "task-corr-999", f"task_id not preserved in normalized '{zcc_event}'"


def test_unknown_zcc_event_returns_none():
    """Unknown ZCC event types return None — forward compatible."""
    result = normalize_zcc_event({"event": "contact_center.unknown_event", "payload": {}})
    assert result is None
