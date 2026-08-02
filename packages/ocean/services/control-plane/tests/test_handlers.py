"""Unit tests for control-plane alert and heartbeat handlers."""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

# Allow importing src package from service root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


def _mock_session() -> AsyncMock:
    """Session whose SELECTs return no rows: no active snooze, no false-positive history.

    A bare AsyncMock's fetchone() yields a truthy coroutine, which reads as an active
    snooze and short-circuits the handler before the task insert.
    """
    result = MagicMock()
    result.fetchone.return_value = None
    session = AsyncMock()
    session.execute.return_value = result
    return session


def _tasks_insert_params(session: AsyncMock) -> dict:
    """Bound params of the INSERT INTO tasks call, wherever it sits in the call list.

    The handler now runs the snooze and false-positive SELECTs before the insert and the
    escalation-state insert after it, so `call_args` (the last call) is never the task row.
    """
    call = next(c for c in session.execute.call_args_list if "INSERT INTO tasks" in str(c[0][0]))
    return call[0][1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_alert_event(alert_type: str = "glucose", alert_id: str = "alert-abc-123") -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "alert.created",
        "timestamp": "2026-03-05T10:00:00Z",
        "source_system": "glucose-connector",
        "entity_id": alert_id,
        "entity_type": "alert",
        "correlation_id": "corr-test-123",
        "payload": {
            "patient_id": "patient-xyz",
            "alert_type": alert_type,
        },
    }


def _make_heartbeat_event(connector_id: str = "glucose-connector") -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "connector.heartbeat",
        "timestamp": "2026-03-05T10:00:00Z",
        "source_system": connector_id,
        "entity_id": connector_id,
        "entity_type": "connector",
        "payload": {
            "connector_id": connector_id,
            "connector_name": "Glucose Connector",
        },
    }


# ---------------------------------------------------------------------------
# Alert handler tests
# ---------------------------------------------------------------------------


class TestHandleAlertCreated:
    @pytest.mark.asyncio
    async def test_glucose_alert_inserts_with_critical_priority(self):
        """handle_alert_created with alert_type='glucose' uses priority='critical'."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        event = _make_alert_event(alert_type="glucose")

        await handle_alert_created(event, session)

        assert session.execute.called
        params = _tasks_insert_params(session)
        assert params["priority"] == "critical"
        assert params["task_type"] == "glucose"
        # status is a literal in the SQL string, not a bound param
        insert_call = next(c for c in session.execute.call_args_list if "INSERT INTO tasks" in str(c[0][0]))
        assert "open" in str(insert_call[0][0])

    @pytest.mark.asyncio
    async def test_unknown_alert_type_uses_medium_priority(self):
        """Unknown alert_type falls back to priority='medium'."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        event = _make_alert_event(alert_type="some_unknown_type")

        await handle_alert_created(event, session)

        params = _tasks_insert_params(session)
        assert params["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_task_id_is_deterministic(self):
        """Same alert_id always produces the same task_id (uuid5 determinism)."""
        from src.handlers.alerts import handle_alert_created

        alert_id = "alert-fixed-id-456"
        event = _make_alert_event(alert_id=alert_id)

        session1 = _mock_session()
        await handle_alert_created(event, session1)
        task_id_1 = _tasks_insert_params(session1)["task_id"]

        session2 = _mock_session()
        await handle_alert_created(event, session2)
        task_id_2 = _tasks_insert_params(session2)["task_id"]

        assert task_id_1 == task_id_2
        # Ensure it's a valid UUID string
        uuid.UUID(task_id_1)

    @pytest.mark.asyncio
    async def test_producer_publish_called_with_task_created(self):
        """After DB write, producer.publish is called with ocean.tasks topic and task.created event_type."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        producer = AsyncMock()
        event = _make_alert_event(alert_type="glucose")

        await handle_alert_created(event, session, producer=producer)

        assert producer.publish.called
        topic, task_event = producer.publish.call_args[0]
        assert topic == "ocean.tasks"
        assert task_event["event_type"] == "task.created"
        assert task_event["entity_type"] == "task"
        assert task_event["schema_version"] == "1.0.0"
        assert task_event["correlation_id"] == "corr-test-123"

    @pytest.mark.asyncio
    async def test_no_producer_does_not_raise(self):
        """Without a producer, handler completes without error."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        event = _make_alert_event()

        await handle_alert_created(event, session, producer=None)

        assert session.execute.called

    @pytest.mark.asyncio
    async def test_alert_id_and_patient_id_in_params(self):
        """alert_id and patient_id are passed through to DB params."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        event = _make_alert_event(alert_id="my-alert-99")
        event["payload"]["patient_id"] = "patient-007"

        await handle_alert_created(event, session)

        params = _tasks_insert_params(session)
        assert params["alert_id"] == "my-alert-99"
        assert params["patient_id"] == "patient-007"

    @pytest.mark.asyncio
    async def test_task_created_payload_includes_channel(self):
        """task.created event payload contains channel field from channel_for()."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        producer = AsyncMock()
        event = _make_alert_event(alert_type="glucose")

        await handle_alert_created(event, session, producer=producer)

        _, task_event = producer.publish.call_args[0]
        assert "channel" in task_event["payload"]
        assert task_event["payload"]["channel"] == "#care-alerts-glucose"

    @pytest.mark.asyncio
    async def test_task_assigned_published_when_assigned_to_present(self):
        """When payload has assigned_to, producer.publish is called twice: task.created + task.assigned."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        producer = AsyncMock()
        event = _make_alert_event(alert_type="glucose")
        event["payload"]["assigned_to"] = "nurse-jane"

        await handle_alert_created(event, session, producer=producer)

        assert producer.publish.call_count == 2
        first_call_event = producer.publish.call_args_list[0][0][1]
        second_call_event = producer.publish.call_args_list[1][0][1]
        assert first_call_event["event_type"] == "task.created"
        assert second_call_event["event_type"] == "task.assigned"
        assert second_call_event["payload"]["assigned_to"] == "nurse-jane"
        assert second_call_event["entity_type"] == "task"
        assert second_call_event["source_system"] == "control-plane"
        assert second_call_event["schema_version"] == "1.0.0"
        assert second_call_event["correlation_id"] == "corr-test-123"

    @pytest.mark.asyncio
    async def test_task_assigned_not_published_when_assigned_to_absent(self):
        """Without assigned_to in payload, producer.publish is called once (task.created only)."""
        from src.handlers.alerts import handle_alert_created

        session = _mock_session()
        producer = AsyncMock()
        event = _make_alert_event(alert_type="glucose")
        # No assigned_to in payload

        await handle_alert_created(event, session, producer=producer)

        assert producer.publish.call_count == 1
        published_event = producer.publish.call_args[0][1]
        assert published_event["event_type"] == "task.created"


# ---------------------------------------------------------------------------
# Heartbeat handler tests
# ---------------------------------------------------------------------------


class TestHandleConnectorHeartbeat:
    @pytest.mark.asyncio
    async def test_connector_id_extracted_from_payload(self):
        """connector_id is taken from payload.connector_id."""
        from src.handlers.heartbeats import handle_connector_heartbeat

        session = AsyncMock()
        event = _make_heartbeat_event(connector_id="bp-connector")

        await handle_connector_heartbeat(event, session)

        assert session.execute.called
        params = session.execute.call_args[0][1]
        assert params["connector_id"] == "bp-connector"

    @pytest.mark.asyncio
    async def test_falls_back_to_source_system_if_no_payload_connector_id(self):
        """Falls back to source_system when payload.connector_id absent."""
        from src.handlers.heartbeats import handle_connector_heartbeat

        session = AsyncMock()
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "connector.heartbeat",
            "timestamp": "2026-03-05T10:00:00Z",
            "source_system": "fallback-connector",
            "entity_id": "fallback-connector",
            "entity_type": "connector",
            "payload": {},  # No connector_id in payload
        }

        await handle_connector_heartbeat(event, session)

        params = session.execute.call_args[0][1]
        assert params["connector_id"] == "fallback-connector"

    @pytest.mark.asyncio
    async def test_upsert_sql_contains_on_conflict(self):
        """SQL statement contains ON CONFLICT DO UPDATE for upsert semantics."""
        from src.handlers.heartbeats import handle_connector_heartbeat

        session = AsyncMock()
        event = _make_heartbeat_event()

        await handle_connector_heartbeat(event, session)

        sql_call = session.execute.call_args[0][0]
        sql_text = str(sql_call)
        assert "ON CONFLICT" in sql_text.upper()
        assert "DO UPDATE" in sql_text.upper()

    @pytest.mark.asyncio
    async def test_last_seen_param_is_set(self):
        """last_seen parameter is set in the upsert params."""
        from src.handlers.heartbeats import handle_connector_heartbeat

        session = AsyncMock()
        event = _make_heartbeat_event()

        await handle_connector_heartbeat(event, session)

        params = session.execute.call_args[0][1]
        assert "last_seen" in params
        assert params["last_seen"] is not None
