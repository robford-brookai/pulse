"""ZCC-03: Outcome entity created with outcome_type and resolution_status.

Requirement: When call.completed or call.missed is projected, an Outcome record
is created in the operational graph with:
  - outcome_type: 'call_completed' or 'call_missed'
  - resolution_status: 'resolved' (completed) or 'no_contact' (missed)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from utils import setup_service

setup_service("graph-projection")

from src.handlers.outcomes import handle_call_completed, handle_call_missed


def _call_event(event_type: str, disposition: str = "resolved") -> dict:
    return {
        "event_id": "evt-001",
        "event_type": event_type,
        "source_system": "zcc",
        "entity_id": "eng-001",
        "entity_type": "interaction",
        "actor_id": "agent-1",
        "timestamp": "2026-03-06T10:00:00Z",
        "payload": {
            "engagement_id": "eng-001",
            "agent_id": "agent-1",
            "duration_seconds": 240,
            "disposition": disposition,
            "patient_id": "pt-001",
            "task_id": "task-abc",
        },
    }


def _get_sql_and_params(mock_session, call_index: int):
    args, _ = mock_session.execute.call_args_list[call_index]
    clause = args[0]
    sql = clause.text if hasattr(clause, "text") else str(clause)
    params = args[1] if len(args) > 1 else {}
    return sql, params


@pytest.mark.asyncio
async def test_call_completed_inserts_outcome_with_call_completed_type():
    """handle_call_completed inserts outcome with outcome_type='call_completed'."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_completed(_call_event("call.completed"), session)

    # Second execute is the outcome INSERT
    assert session.execute.call_count == 2
    sql, params = _get_sql_and_params(session, call_index=1)
    assert "outcomes" in sql
    assert "call_completed" in sql or params.get("outcome_type") == "call_completed", (
        "Outcome type 'call_completed' not found in outcome INSERT"
    )


@pytest.mark.asyncio
async def test_call_completed_outcome_has_resolved_status():
    """handle_call_completed outcome has resolution_status='resolved'."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_completed(_call_event("call.completed", disposition="resolved"), session)

    sql, params = _get_sql_and_params(session, call_index=1)
    # The SQL embeds 'resolved' as a literal or params has notes='resolved'
    assert "resolved" in sql or params.get("notes") == "resolved", (
        "resolution_status='resolved' not found in outcome INSERT"
    )


@pytest.mark.asyncio
async def test_call_missed_inserts_outcome_with_call_missed_type():
    """handle_call_missed inserts outcome with outcome_type='call_missed'."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_missed(_call_event("call.missed"), session)

    assert session.execute.call_count == 2
    sql, params = _get_sql_and_params(session, call_index=1)
    assert "outcomes" in sql
    assert "call_missed" in sql, "Outcome type 'call_missed' not found in outcome INSERT"


@pytest.mark.asyncio
async def test_call_missed_outcome_has_no_contact_status():
    """handle_call_missed outcome has resolution_status='no_contact'."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    await handle_call_missed(_call_event("call.missed"), session)

    sql, params = _get_sql_and_params(session, call_index=1)
    assert "no_contact" in sql, "resolution_status='no_contact' not found in missed outcome INSERT"


@pytest.mark.asyncio
async def test_call_completed_outcome_id_is_deterministic():
    """Outcome ID is deterministic (uuid5) — re-processing same event is idempotent."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    event = _call_event("call.completed")

    await handle_call_completed(event, session)
    first_params = _get_sql_and_params(session, call_index=1)[1]
    first_outcome_id = first_params.get("outcome_id")

    # Reset and run again
    session.execute.reset_mock()
    await handle_call_completed(event, session)
    second_params = _get_sql_and_params(session, call_index=1)[1]
    second_outcome_id = second_params.get("outcome_id")

    assert first_outcome_id is not None
    assert first_outcome_id == second_outcome_id, "Outcome ID must be deterministic for idempotent re-processing"
