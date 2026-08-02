"""Unit tests for graph projection handlers and consumer dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


def make_alert_event(alert_id="a1", patient_id="p1", clinic_id="c1"):
    return {
        "event_id": "evt-001",
        "event_type": "alert.created",
        "source_system": "pocar",
        "entity_id": alert_id,
        "entity_type": "alert",
        "correlation_id": "corr-001",
        "timestamp": "2026-03-05T10:00:00Z",
        "payload": {
            "alert_type": "glucose_missing",
            "severity": "urgent",
            "patient_id": patient_id,
            "clinic_id": clinic_id,
        },
    }


@pytest.mark.asyncio
async def test_handle_alert_created_maps_fields(mock_session):
    """handle_alert_created calls session.execute with patients bootstrap + alerts upsert + audit_log."""
    from src.handlers.alerts import handle_alert_created

    await handle_alert_created(make_alert_event(), mock_session)
    assert mock_session.execute.call_count == 3  # patients bootstrap + alerts upsert + audit_log

    all_calls_str = str(mock_session.execute.call_args_list)
    assert "p1" in all_calls_str
    assert "a1" in all_calls_str


@pytest.mark.asyncio
async def test_handle_alert_created_idempotent(mock_session):
    """Calling handle_alert_created twice does not raise — ON CONFLICT handles dedup at DB level."""
    from src.handlers.alerts import handle_alert_created

    event = make_alert_event()
    await handle_alert_created(event, mock_session)
    await handle_alert_created(event, mock_session)
    # Both calls complete without error; DB-level idempotency via ON CONFLICT DO UPDATE
    assert mock_session.execute.call_count == 6  # 3 per call x 2


@pytest.mark.asyncio
async def test_unknown_event_type_skipped(mock_session):
    """dispatch() with unknown event_type does not raise and does not call session.execute."""
    from src.consumer import dispatch

    await dispatch({"event_type": "future.event.type", "payload": {}}, mock_session)
    mock_session.execute.assert_not_called()


def test_consumer_group_id_is_graph_projection_worker():
    """Consumer config declares correct group.id to avoid sharing offsets with event-store-consumer."""
    from src.consumer import CONSUMER_CONFIG

    assert CONSUMER_CONFIG["group.id"] == "graph-projection-worker"


@pytest.mark.asyncio
async def test_handle_task_claimed_updates_status(mock_session):
    """handle_task_claimed updates task status to 'claimed' and sets assigned_to from actor_id."""
    from src.handlers.tasks import handle_task_claimed

    event = {
        "event_id": "evt-claimed-001",
        "event_type": "task.claimed",
        "entity_id": "task-abc",
        "entity_type": "task",
        "timestamp": "2026-03-05T10:00:00Z",
        "payload": {"task_id": "task-abc", "actor_id": "nurse-jane"},
    }

    await handle_task_claimed(event, mock_session)

    assert mock_session.execute.called
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "claimed" in sql_text
    params = mock_session.execute.call_args[0][1]
    assert params["task_id"] == "task-abc"
    assert params["assigned_to"] == "nurse-jane"
    assert params["event_id"] == "evt-claimed-001"


def test_task_claimed_registered_in_event_handlers():
    """task.claimed is registered in EVENT_HANDLERS and dispatches to handle_task_claimed."""
    from src.consumer import EVENT_HANDLERS
    from src.handlers.tasks import handle_task_claimed

    assert "task.claimed" in EVENT_HANDLERS
    assert EVENT_HANDLERS["task.claimed"] is handle_task_claimed
