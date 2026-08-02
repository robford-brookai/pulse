"""Tests for event-store writer module."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch


SAMPLE_EVENT = {
    "event_id": "evt-001",
    "event_type": "signal.received",
    "schema_version": "1.0.0",
    "entity_type": "patient",
    "entity_id": "pat-001",
    "source_system": "pocar",
    "correlation_id": "corr-001",
    "actor_id": "user-001",
    "timestamp": "2026-03-15T10:00:00Z",
    "payload": {"key": "value"},
}


def _make_session_maker():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    session.begin = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    maker = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return maker, session


async def test_write_event_executes_two_inserts():
    maker, session = _make_session_maker()
    with patch("src.writer._get_session_maker", return_value=maker):
        from src.writer import write_event
        await write_event(json.dumps(SAMPLE_EVENT).encode(), topic="ocean.signals")
    assert session.execute.call_count == 2


async def test_write_event_maps_fields_correctly():
    maker, session = _make_session_maker()
    with patch("src.writer._get_session_maker", return_value=maker):
        from src.writer import write_event
        await write_event(json.dumps(SAMPLE_EVENT).encode(), topic="ocean.signals")

    # First call is the events table insert
    first_call_params = session.execute.call_args_list[0][0][1]
    assert first_call_params["event_id"] == "evt-001"
    assert first_call_params["event_type"] == "signal.received"
    assert first_call_params["entity_type"] == "patient"
    assert first_call_params["entity_id"] == "pat-001"
    assert first_call_params["source_system"] == "pocar"
    assert first_call_params["payload"] == json.dumps({"key": "value"})


async def test_write_event_audit_log_action_type():
    maker, session = _make_session_maker()
    with patch("src.writer._get_session_maker", return_value=maker):
        from src.writer import write_event
        await write_event(json.dumps(SAMPLE_EVENT).encode(), topic="ocean.signals")

    second_call_params = session.execute.call_args_list[1][0][1]
    assert second_call_params["action_type"] == "event.ingested"


async def test_write_event_actor_id_fallback():
    event = {k: v for k, v in SAMPLE_EVENT.items() if k != "actor_id"}
    maker, session = _make_session_maker()
    with patch("src.writer._get_session_maker", return_value=maker):
        from src.writer import write_event
        await write_event(json.dumps(event).encode(), topic="ocean.signals")

    second_call_params = session.execute.call_args_list[1][0][1]
    assert second_call_params["actor_id"] == "system"


async def test_write_event_minimal_payload():
    minimal = {
        "event_id": "evt-min",
        "event_type": "signal.received",
        "timestamp": "2026-03-15T10:00:00Z",
    }
    maker, session = _make_session_maker()
    with patch("src.writer._get_session_maker", return_value=maker):
        from src.writer import write_event
        # Should not raise
        await write_event(json.dumps(minimal).encode(), topic="ocean.signals")
    assert session.execute.call_count == 2
