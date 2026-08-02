"""stacte-bridge business logic: entity_to_text embedding construction.

Sourced from test/cat6_business_logic.py.
"""

from __future__ import annotations

from utils import setup_service

setup_service("stacte-bridge")

from src.embedder import entity_to_text


def test_alert_entity_to_text_contains_severity_and_type():
    text = entity_to_text(
        "alerts",
        {
            "alert_id": "a1",
            "patient_id": "patient-12345678",
            "alert_type": "glucose_high",
            "severity": "URGENT",
            "status": "open",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    assert "URGENT" in text
    assert "glucose_high" in text
    assert "patient=" in text


def test_task_entity_to_text_contains_type_and_priority():
    text = entity_to_text(
        "tasks",
        {
            "task_id": "t1",
            "task_type": "outreach",
            "priority": "high",
            "status": "claimed",
            "alert_id": "alert-abcdefgh",
        },
    )
    assert "outreach" in text
    assert "high" in text
    assert "alert-ab" in text


def test_outcome_entity_to_text_contains_type_and_resolution():
    text = entity_to_text(
        "outcomes",
        {
            "outcome_id": "o1",
            "outcome_type": "call_completed",
            "resolution_status": "resolved",
            "notes": None,
        },
    )
    assert "call_completed" in text
    assert "resolved" in text
