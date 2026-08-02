"""ZCC normalizer: duration and disposition fields (ZCC-03 supplement).

Sourced from test/cat6_business_logic.py. The 4 event-type mapping tests
are omitted (covered by tests/requirements/test_INGEST_02.py).
This file covers the unique duration/disposition payload assertion.
"""
from __future__ import annotations

from utils import setup_service

setup_service("zcc-connector")

from src.normalizer import normalize_zcc_event  # noqa: E402


def _zcc_payload(event_name: str, engagement_id: str = "eng-001") -> dict:
    return {
        "event": event_name,
        "payload": {
            "object": {
                "engagement_id": engagement_id,
                "assigned_to": {"id": "agent-001"},
                "duration": 120,
                "disposition_name": "resolved",
                "patient_id": "pt-001",
                "task_id": "task-001",
            }
        },
    }


def test_zcc_normalized_payload_has_duration_and_disposition():
    """Outcome fields present in payload (ZCC-03)."""
    result = normalize_zcc_event(_zcc_payload("contact_center.engagement_ended"))
    assert result is not None
    assert result["payload"]["duration_seconds"] == 120
    assert result["payload"]["disposition"] == "resolved"
