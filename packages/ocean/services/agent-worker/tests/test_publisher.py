"""Tests for agent-worker's publisher wiring.

agent-worker holds no transport code of its own after the EventBridge migration: ``publisher.py``
resolves the DLQ session maker and hands back ocean-broker's ``EventBridgePublisher``. These tests
assert that wiring, and that the service's publish sites address the bus by domain rather than by
the old ``ocean.<domain>`` topic name.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ocean_broker import EventBridgePublisher
from src.publisher import build_publisher


@pytest.fixture
def mock_events_client():
    """boto3 ``events`` client that accepts every PutEvents call."""
    client = MagicMock()
    client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
    return client


@pytest.fixture
def mock_db_session_maker():
    """Async session maker whose session records the statements executed against it."""
    session = AsyncMock()
    session.execute = AsyncMock()

    begin = AsyncMock()
    begin.__aenter__ = AsyncMock(return_value=None)
    begin.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin)

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            return None

    maker = MagicMock(side_effect=_Ctx)
    maker.session = session
    return maker


class TestBuildPublisher:
    def test_returns_the_shared_publisher(self, monkeypatch, mock_events_client):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch("boto3.client", return_value=mock_events_client):
            publisher = build_publisher()

        assert isinstance(publisher, EventBridgePublisher)

    def test_dlq_attached_when_database_url_is_set(self, monkeypatch, mock_events_client):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ocean:ocean@db:5432/ocean")
        with patch("boto3.client", return_value=mock_events_client):
            publisher = build_publisher()

        assert publisher._db_session_maker is not None

    def test_no_dlq_without_a_database_url(self, monkeypatch, mock_events_client):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch("boto3.client", return_value=mock_events_client):
            publisher = build_publisher()

        assert publisher._db_session_maker is None


class TestPublishSitesAddressByDomain:
    """The service's event builders publish through the shared publisher."""

    @staticmethod
    def _task_data() -> dict:
        return {"entity_id": "task-001", "correlation_id": "corr-001"}

    @staticmethod
    def _persona():
        from src.personas import Persona

        return Persona(
            id="coordinator_alice",
            role="coordinator",
            call_answer_rate=0.7,
            missed_call_retry_count=2,
            retry_delay_seconds=60,
        )

    async def test_ai_ops_event_carries_the_envelope_whole(self, mock_events_client):
        from src.events import publish_ai_recommendation

        with patch("boto3.client", return_value=mock_events_client):
            publisher = EventBridgePublisher()

        await publish_ai_recommendation(publisher, self._task_data(), "approve", 0.9, self._persona())

        entry = mock_events_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["Source"] == "ocean"
        assert entry["DetailType"] == "ai-ops"
        envelope = json.loads(entry["Detail"])
        assert envelope["event_type"] == "ai.recommendation.generated"
        assert envelope["payload"]["confidence"] == 0.9

    async def test_task_completed_addresses_the_tasks_domain(self, mock_events_client):
        from src.events import publish_task_completed

        with patch("boto3.client", return_value=mock_events_client):
            publisher = EventBridgePublisher()

        await publish_task_completed(publisher, self._task_data(), self._persona())

        entry = mock_events_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["DetailType"] == "tasks"
        assert json.loads(entry["Detail"])["event_type"] == "task.completed"

    async def test_claim_addresses_the_tasks_domain(self, mock_events_client):
        from src.claim import compete_for_claim

        with patch("boto3.client", return_value=mock_events_client):
            publisher = EventBridgePublisher()

        event = {
            "entity_id": "task-001",
            "correlation_id": "corr-001",
            "payload": {"task_type": "glucose", "severity": "URGENT"},
        }
        await compete_for_claim(event, [self._persona()], publisher, set())

        entry = mock_events_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["DetailType"] == "tasks"
        assert json.loads(entry["Detail"])["event_type"] == "task.claimed"


class TestPublishFailureFallsBackToFailedWebhooks:
    """agent-worker had no dead-letter fallback under Kafka; it inherits one here."""

    async def test_bus_failure_writes_failed_webhooks_and_does_not_raise(self, mock_db_session_maker):
        from src.events import publish_task_completed

        client = MagicMock()
        client.put_events = MagicMock(side_effect=RuntimeError("bus unavailable"))
        with patch("boto3.client", return_value=client):
            publisher = EventBridgePublisher(db_session_maker=mock_db_session_maker)

        from src.personas import Persona

        persona = Persona(
            id="coordinator_alice",
            role="coordinator",
            call_answer_rate=0.7,
            missed_call_retry_count=2,
            retry_delay_seconds=60,
        )
        await publish_task_completed(publisher, {"entity_id": "task-001", "correlation_id": "c"}, persona)

        mock_db_session_maker.session.execute.assert_awaited_once()
        statement = str(mock_db_session_maker.session.execute.await_args.args[0])
        assert "failed_webhooks" in statement
