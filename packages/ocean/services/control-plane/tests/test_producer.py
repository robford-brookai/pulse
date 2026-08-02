"""Unit tests for the control-plane publish site (task 4.7, DNA-750).

The service no longer owns transport code: `ControlPlanePublisher` is a naming adapter over the
shared `EventBridgePublisher`. Call sites still name their destination by the former Kafka topic
(`ocean.tasks`), so these tests pin the topic → domain translation, the untouched payload, and
the `failed_webhooks` fallback the site gains by inheritance.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.producer import ControlPlanePublisher, domain_for_topic


@pytest.fixture
def mock_eventbridge_client():
    """A boto3 EventBridge client that accepts every entry."""
    client = MagicMock()
    client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
    return client


@pytest.fixture
def mock_db_session_maker():
    """An async session maker whose session records `execute` calls."""
    session = AsyncMock()
    session.execute = AsyncMock()

    begin_context = AsyncMock()
    begin_context.__aenter__ = AsyncMock(return_value=None)
    begin_context.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_context)

    class SessionContextManager:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            pass

    maker = MagicMock(side_effect=SessionContextManager)
    maker._test_session = session
    return maker


def make_publisher(client, session_maker=None) -> ControlPlanePublisher:
    """Build a publisher whose bus client is the supplied mock."""
    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        mock_boto3.client.return_value = client
        publisher = ControlPlanePublisher(db_session_maker=session_maker, region="us-east-1")
    return publisher


def sole_entry(client) -> dict:
    """Return the single PutEvents entry the client was called with."""
    client.put_events.assert_called_once()
    entries = client.put_events.call_args.kwargs["Entries"]
    assert len(entries) == 1
    return entries[0]


class TestTopicTranslation:
    """The former topic name resolves to the catalog domain, and nothing else."""

    @pytest.mark.parametrize(
        ("topic", "domain"),
        [
            ("ocean.tasks", "tasks"),
            ("ocean.outcomes", "outcomes"),
            ("ocean.tickets", "tickets"),
            ("ocean.patient-state", "patient-state"),
            ("tasks", "tasks"),
        ],
    )
    def test_domain_for_topic(self, topic, domain):
        assert domain_for_topic(topic) == domain

    def test_unknown_topic_is_rejected_before_the_bus(self, mock_eventbridge_client):
        """An address no rule matches is a dead publish, so it fails loudly at resolution."""
        with pytest.raises(KeyError):
            domain_for_topic("ocean.warehouse-dlq")


class TestPublishesThroughSharedPublisher:
    """Every emit goes through EventBridgePublisher with the payload unchanged."""

    @pytest.mark.asyncio
    async def test_emits_through_shared_publisher(self, mock_eventbridge_client):
        publisher = make_publisher(mock_eventbridge_client)
        envelope = {
            "event_id": "6f1a3f3e-0000-4000-8000-000000000001",
            "event_type": "task.created",
            "schema_version": "1.0.0",
            "source_system": "control-plane",
            "entity_type": "task",
            "entity_id": "task-1",
            "payload": {"priority": "high"},
        }

        await publisher.publish("ocean.tasks", envelope)

        entry = sole_entry(mock_eventbridge_client)
        assert entry["Source"] == "ocean"
        assert entry["DetailType"] == "tasks"
        assert json.loads(entry["Detail"]) == envelope

    @pytest.mark.asyncio
    async def test_event_type_is_not_promoted_to_detail_type(self, mock_eventbridge_client):
        publisher = make_publisher(mock_eventbridge_client)

        await publisher.publish("ocean.outcomes", {"event_type": "call.completed"})

        entry = sole_entry(mock_eventbridge_client)
        assert entry["DetailType"] == "outcomes"
        assert json.loads(entry["Detail"])["event_type"] == "call.completed"

    @pytest.mark.asyncio
    async def test_key_is_carried_as_an_envelope_field(self, mock_eventbridge_client):
        publisher = make_publisher(mock_eventbridge_client)

        await publisher.publish("ocean.tasks", {"event_type": "task.created"}, key="task-1")

        assert json.loads(sole_entry(mock_eventbridge_client)["Detail"])["key"] == "task-1"

    def test_no_bus_client_in_service_code(self):
        """The service holds no transport code of its own."""
        from pathlib import Path

        from src import producer

        source = Path(producer.__file__).read_text(encoding="utf-8")
        assert "confluent_kafka" not in source
        assert "boto3" not in source


class TestFailurePath:
    """The site had no dead-letter fallback under Kafka; it gains one here."""

    @pytest.mark.asyncio
    async def test_bus_failure_writes_failed_webhooks(self, mock_eventbridge_client, mock_db_session_maker):
        mock_eventbridge_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "500", "ErrorMessage": "bus unavailable"}],
        }
        publisher = make_publisher(mock_eventbridge_client, mock_db_session_maker)

        await publisher.publish("ocean.tasks", {"event_type": "task.created"}, key="task-1")

        session = mock_db_session_maker._test_session
        session.execute.assert_called_once()
        statement, params = session.execute.call_args[0]
        assert "INSERT INTO failed_webhooks" in str(statement)
        assert params["key"] == "task-1"
        assert params["error"] == "bus unavailable"

    @pytest.mark.asyncio
    async def test_bus_exception_does_not_reach_the_caller(self, mock_eventbridge_client, mock_db_session_maker):
        mock_eventbridge_client.put_events.side_effect = RuntimeError("connection reset")
        publisher = make_publisher(mock_eventbridge_client, mock_db_session_maker)

        await publisher.publish("ocean.outcomes", {"event_type": "call.completed"})

        mock_db_session_maker._test_session.execute.assert_called_once()
