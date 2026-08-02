"""Unit tests for graph-projection ops event handlers."""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_heartbeat_event(
    connector_id: str = "pocar",
    connector_name: str = "POCAR Connector",
) -> dict:
    return {
        "event_id": "evt-hb-001",
        "event_type": "connector.heartbeat",
        "source_system": "pocar",
        "timestamp": "2026-03-15T10:00:00Z",
        "payload": {
            "connector_id": connector_id,
            "connector_name": connector_name,
        },
    }


def _make_scenario_completed_event(
    scenario_name: str = "full_cohort",
) -> dict:
    return {
        "event_id": "evt-sc-001",
        "event_type": "scenario.completed",
        "source_system": "sim-driver",
        "entity_id": scenario_name,
        "timestamp": "2026-03-15T10:05:00Z",
        "payload": {
            "scenario_name": scenario_name,
            "patients_count": 5,
            "alerts_generated": 3,
            "tasks_created": 3,
            "duration_seconds": 12.5,
        },
    }


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


# ---------------------------------------------------------------------------
# handler tests
# ---------------------------------------------------------------------------


async def test_handle_connector_heartbeat_upserts():
    from src.handlers.ops import handle_connector_heartbeat

    session = _mock_session()
    await handle_connector_heartbeat(_make_heartbeat_event(), session)
    session.execute.assert_awaited_once()
    params = session.execute.call_args[0][1]
    assert params["connector_id"] == "pocar"
    assert params["connector_name"] == "POCAR Connector"


async def test_handle_connector_heartbeat_falls_back_to_source_system():
    from src.handlers.ops import handle_connector_heartbeat

    event = _make_heartbeat_event()
    event["payload"] = {}  # no connector_id in payload
    session = _mock_session()
    await handle_connector_heartbeat(event, session)
    params = session.execute.call_args[0][1]
    assert params["connector_id"] == "pocar"  # falls back to source_system


async def test_handle_scenario_completed_upserts():
    from src.handlers.ops import handle_scenario_completed

    session = _mock_session()
    await handle_scenario_completed(_make_scenario_completed_event(), session)
    session.execute.assert_awaited_once()
    params = session.execute.call_args[0][1]
    assert params["scenario_name"] == "full_cohort"
    assert params["patients_count"] == 5
    assert params["duration_seconds"] == 12.5


async def test_handle_scenario_completed_idempotent():
    from src.handlers.ops import handle_scenario_completed

    session = _mock_session()
    event = _make_scenario_completed_event()
    await handle_scenario_completed(event, session)
    await handle_scenario_completed(event, session)
    assert session.execute.await_count == 2  # two calls, no raises


async def test_connector_heartbeat_registered():
    from src.consumer import EVENT_HANDLERS

    assert "connector.heartbeat" in EVENT_HANDLERS


async def test_scenario_completed_registered():
    from src.consumer import EVENT_HANDLERS

    assert "scenario.completed" in EVENT_HANDLERS


async def test_ocean_ops_in_topics():
    from src.consumer import TOPICS

    assert "ocean.ops" in TOPICS
