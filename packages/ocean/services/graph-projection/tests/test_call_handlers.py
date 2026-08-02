"""Unit tests for graph projection call lifecycle handlers (interactions + outcomes)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


def _make_call_event(event_type: str, entity_id: str = "eng-1", **payload_overrides) -> dict:
    payload = {
        "engagement_id": entity_id,
        "agent_id": "agent-1",
        "duration_seconds": 120,
        "disposition": "resolved",
        "patient_id": "pt-001",
        "task_id": "",
    }
    payload.update(payload_overrides)
    return {
        "event_id": "evt-001",
        "event_type": event_type,
        "source_system": "zcc",
        "entity_id": entity_id,
        "entity_type": "interaction",
        "actor_id": "agent-1",
        "timestamp": "2026-03-05T10:00:00Z",
        "payload": payload,
    }


def _get_sql_and_params(mock_session, call_index: int = 0):
    """Extract SQL string and params dict from a mock session.execute() call."""
    args, kwargs = mock_session.execute.call_args_list[call_index]
    sql_clause = args[0]
    params = args[1] if len(args) > 1 else {}
    # TextClause stores text in .text attribute
    sql_str = sql_clause.text if hasattr(sql_clause, "text") else str(sql_clause)
    return sql_str, params


@pytest.mark.asyncio
async def test_handle_call_started_upserts_interaction(mock_session):
    """call.started projects an Interaction record with interaction_type='call'."""
    from src.handlers.interactions import handle_call_started

    await handle_call_started(_make_call_event("call.started"), mock_session)
    mock_session.execute.assert_called_once()
    sql, params = _get_sql_and_params(mock_session)
    assert "interactions" in sql
    assert params["interaction_id"] == "eng-1"


@pytest.mark.asyncio
async def test_handle_call_connected_upserts_interaction(mock_session):
    """call.connected updates interaction with started_at (no outcome)."""
    from src.handlers.interactions import handle_call_connected

    await handle_call_connected(_make_call_event("call.connected"), mock_session)
    mock_session.execute.assert_called_once()
    sql, params = _get_sql_and_params(mock_session)
    assert "interactions" in sql


@pytest.mark.asyncio
async def test_handle_call_completed_upserts_interaction_and_inserts_outcome(mock_session):
    """call.completed creates Interaction with outcome='completed' AND Outcome record."""
    from src.handlers.outcomes import handle_call_completed

    await handle_call_completed(_make_call_event("call.completed", disposition="resolved"), mock_session)
    # Two executes: interaction upsert + outcome insert
    assert mock_session.execute.call_count == 2
    sql0, params0 = _get_sql_and_params(mock_session, 0)
    sql1, params1 = _get_sql_and_params(mock_session, 1)
    assert "interactions" in sql0
    assert "completed" in sql0
    assert "outcomes" in sql1
    assert "resolved" in sql1 or params1.get("notes") == "resolved"


@pytest.mark.asyncio
async def test_handle_call_missed_creates_missed_outcome(mock_session):
    """call.missed creates Interaction with outcome='missed' AND Outcome with no_contact."""
    from src.handlers.outcomes import handle_call_missed

    await handle_call_missed(_make_call_event("call.missed"), mock_session)
    assert mock_session.execute.call_count == 2
    sql0, params0 = _get_sql_and_params(mock_session, 0)
    sql1, params1 = _get_sql_and_params(mock_session, 1)
    assert "missed" in sql0
    assert "no_contact" in sql1


@pytest.mark.asyncio
async def test_task_id_correlation(mock_session):
    """When payload contains task_id, interactions.task_id is set to that value."""
    from src.handlers.interactions import handle_call_started

    event = _make_call_event("call.started", task_id="task-xyz-001")
    await handle_call_started(event, mock_session)
    _, params = _get_sql_and_params(mock_session)
    assert params["task_id"] == "task-xyz-001"


@pytest.mark.asyncio
async def test_consumer_handles_call_events():
    """consumer.py EVENT_HANDLERS contains all 4 call lifecycle event types."""
    from src.consumer import EVENT_HANDLERS

    assert "call.started" in EVENT_HANDLERS
    assert "call.connected" in EVENT_HANDLERS
    assert "call.completed" in EVENT_HANDLERS
    assert "call.missed" in EVENT_HANDLERS
