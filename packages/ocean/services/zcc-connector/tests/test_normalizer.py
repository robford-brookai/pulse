"""Tests for ZCC normalizer — event type mapping and payload extraction."""
from __future__ import annotations

import pytest


def _make_raw(event: str = "contact_center.engagement_ended") -> dict:
    return {
        "event": event,
        "payload": {
            "account_id": "acc-001",
            "object": {
                "engagement_id": "eng-1",
                "assigned_to": {"id": "agent-1"},
                "duration": 120,
                "disposition_name": "resolved",
            },
        },
    }


def test_normalize_engagement_ended():
    """contact_center.engagement_ended maps to call.completed with correct fields."""
    from src.normalizer import normalize_zcc_event

    result = normalize_zcc_event(_make_raw("contact_center.engagement_ended"))
    assert result is not None
    assert result["event_type"] == "call.completed"
    assert result["entity_id"] == "eng-1"
    assert result["payload"]["engagement_id"] == "eng-1"
    assert result["source_system"] == "zcc"
    assert result["entity_type"] == "interaction"
    assert result["actor_id"] == "agent-1"


def test_normalize_engagement_started():
    """contact_center.engagement_started maps to call.started."""
    from src.normalizer import normalize_zcc_event

    raw = _make_raw("contact_center.engagement_started")
    result = normalize_zcc_event(raw)
    assert result is not None
    assert result["event_type"] == "call.started"


def test_normalize_engagement_answered():
    """contact_center.engagement_answered maps to call.connected."""
    from src.normalizer import normalize_zcc_event

    raw = _make_raw("contact_center.engagement_answered")
    result = normalize_zcc_event(raw)
    assert result is not None
    assert result["event_type"] == "call.connected"


def test_normalize_engagement_missed():
    """contact_center.engagement_missed maps to call.missed."""
    from src.normalizer import normalize_zcc_event

    raw = _make_raw("contact_center.engagement_missed")
    result = normalize_zcc_event(raw)
    assert result is not None
    assert result["event_type"] == "call.missed"


def test_normalize_unknown_event():
    """Unknown ZCC event name returns None."""
    from src.normalizer import normalize_zcc_event

    result = normalize_zcc_event(_make_raw("contact_center.unknown"))
    assert result is None
