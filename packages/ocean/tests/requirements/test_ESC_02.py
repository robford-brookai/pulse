"""ESC-02: Escalation publishes task.escalated/ticket.escalated events.

Verifies check_and_escalate publishes events with upgraded priority
to ocean.tasks / ocean.tickets topics.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "services/control-plane")


@pytest.fixture
def _patch_env(monkeypatch):
    monkeypatch.setenv("ESCALATION_TIMEOUT_CRITICAL", "300")
    monkeypatch.setenv("ESCALATION_TIMEOUT_HIGH", "900")
    monkeypatch.setenv("ESCALATION_TIMEOUT_MEDIUM", "1800")
    monkeypatch.setenv("ESCALATION_TIMEOUT_LOW", "3600")
    monkeypatch.setenv("ESCALATION_ENABLED", "true")


@pytest.mark.usefixtures("_patch_env")
async def test_check_and_escalate_publishes_task_escalated():
    """check_and_escalate publishes task.escalated with upgraded priority to ocean.tasks."""
    import importlib
    import src.escalation as esc_mod
    importlib.reload(esc_mod)
    from src.escalation import check_and_escalate

    # Use a created_at far enough in the past that any real now() will exceed the threshold
    created_at = datetime.now(tz=UTC) - timedelta(hours=2)

    candidate_row = MagicMock()
    candidate_row._mapping = {
        "entity_type": "task",
        "entity_id": "task-100",
        "current_priority": "medium",
        "created_at": created_at,
        "escalated_at": None,
        "escalation_count": 0,
    }
    candidate_row.current_priority = "medium"
    candidate_row.escalated_at = None
    candidate_row.created_at = created_at

    find_result = MagicMock()
    find_result.fetchall.return_value = [candidate_row]

    # Mock status check -- task is still "open" (unclaimed)
    status_result = MagicMock()
    status_result.scalar_one_or_none.return_value = "open"

    # Mock the update execute
    update_result = MagicMock()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[find_result, status_result, update_result])

    publisher = AsyncMock()

    count = await check_and_escalate(session, publisher)

    assert count == 1
    publisher.publish.assert_called_once()
    call_args = publisher.publish.call_args
    topic = call_args[0][0]
    event = call_args[0][1]

    assert topic == "ocean.tasks"
    assert event["event_type"] == "task.escalated"
    assert event["payload"]["old_priority"] == "medium"
    assert event["payload"]["new_priority"] == "high"


@pytest.mark.usefixtures("_patch_env")
async def test_check_and_escalate_publishes_ticket_escalated():
    """check_and_escalate publishes ticket.escalated to ocean.tickets."""
    import importlib
    import src.escalation as esc_mod
    importlib.reload(esc_mod)
    from src.escalation import check_and_escalate

    created_at = datetime.now(tz=UTC) - timedelta(hours=3)

    candidate_row = MagicMock()
    candidate_row._mapping = {
        "entity_type": "ticket",
        "entity_id": "ticket-200",
        "current_priority": "low",
        "created_at": created_at,
        "escalated_at": None,
        "escalation_count": 0,
    }
    candidate_row.current_priority = "low"
    candidate_row.escalated_at = None
    candidate_row.created_at = created_at

    find_result = MagicMock()
    find_result.fetchall.return_value = [candidate_row]

    status_result = MagicMock()
    status_result.scalar_one_or_none.return_value = "open"

    update_result = MagicMock()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[find_result, status_result, update_result])

    publisher = AsyncMock()

    count = await check_and_escalate(session, publisher)

    assert count == 1
    call_args = publisher.publish.call_args
    topic = call_args[0][0]
    event = call_args[0][1]

    assert topic == "ocean.tickets"
    assert event["event_type"] == "ticket.escalated"
    assert event["payload"]["old_priority"] == "low"
    assert event["payload"]["new_priority"] == "medium"
