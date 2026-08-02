"""ZCC-02: call.completed links to originating task via task_id.

Requirement: When a ZCC engagement ends (call.completed or call.started),
the Interaction record written to the operational graph must include the
task_id from the event payload, establishing the FK relationship that links
call data back to the originating care coordination task.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import setup_service

setup_service("graph-projection")

from src.handlers.interactions import handle_call_started, handle_call_connected  # noqa: E402
from src.handlers.outcomes import handle_call_completed  # noqa: E402


def _call_event(event_type: str, task_id: str = "task-xyz-001", entity_id: str = "eng-001") -> dict:
    return {
        "event_id": "evt-001",
        "event_type": event_type,
        "source_system": "zcc",
        "entity_id": entity_id,
        "entity_type": "interaction",
        "actor_id": "agent-1",
        "timestamp": "2026-03-06T10:00:00Z",
        "payload": {
            "engagement_id": entity_id,
            "agent_id": "agent-1",
            "duration_seconds": 180,
            "disposition": "resolved",
            "patient_id": "pt-001",
            "task_id": task_id,
        },
    }


def _get_params(mock_session, call_index: int = 0) -> dict:
    args, _ = mock_session.execute.call_args_list[call_index]
    return args[1] if len(args) > 1 else {}


@pytest.mark.asyncio
async def test_call_started_sets_task_id_fk():
    """handle_call_started writes task_id into interactions.task_id."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_started(_call_event("call.started", task_id="task-corr-001"), session)

    params = _get_params(session)
    assert params.get("task_id") == "task-corr-001", (
        f"Expected task_id='task-corr-001', got: {params.get('task_id')}"
    )


@pytest.mark.asyncio
async def test_call_connected_sets_task_id_fk():
    """handle_call_connected writes task_id into interactions.task_id."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_connected(_call_event("call.connected", task_id="task-corr-002"), session)

    params = _get_params(session)
    assert params.get("task_id") == "task-corr-002"


@pytest.mark.asyncio
async def test_call_completed_sets_task_id_fk():
    """handle_call_completed writes task_id into interactions.task_id (first execute)."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_completed(_call_event("call.completed", task_id="task-corr-003"), session)

    # First execute is the interaction upsert
    params = _get_params(session, call_index=0)
    assert params.get("task_id") == "task-corr-003"


@pytest.mark.asyncio
async def test_call_started_empty_task_id_stored_as_empty_string():
    """When task_id is absent from payload, interactions.task_id is empty string."""
    event = _call_event("call.started", task_id="")
    event["payload"].pop("task_id", None)  # Remove entirely to simulate missing field

    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_started(event, session)

    params = _get_params(session)
    assert params.get("task_id") == "" or params.get("task_id") is None, (
        "Missing task_id should yield empty string or None, not raise"
    )
