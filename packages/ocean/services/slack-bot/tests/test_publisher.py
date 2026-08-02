"""Tests for slack-bot's EventBridge publish adapter.

The adapter owns no transport of its own: it translates the legacy Kafka topic names the
call sites still pass into the domain the shared publisher addresses by, and delegates.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.publisher import EventPublisher, domain_for_topic


@pytest.fixture
def bus_client():
    """Mock EventBridge client that accepts every entry."""
    client = MagicMock()
    client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
    return client


@pytest.fixture
def session_maker():
    """Async session maker whose session records every execute() call."""
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

    maker = MagicMock(side_effect=lambda: _Ctx())
    maker.session = session
    return maker


def _publisher(bus_client, session_maker=None):
    with patch("ocean_broker.publisher.boto3.client", return_value=bus_client):
        return EventPublisher(db_session_maker=session_maker)


class TestTopicTranslation:
    def test_legacy_topic_maps_to_domain(self):
        assert domain_for_topic("ocean.tickets") == "tickets"

    def test_bare_domain_passes_through(self):
        assert domain_for_topic("tickets") == "tickets"


class TestPublish:
    async def test_emits_through_shared_publisher(self, bus_client):
        event = {"event_type": "ticket.update.requested", "entity_id": "t-1"}

        await _publisher(bus_client).publish("ocean.tickets", event)

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["Source"] == "ocean"
        assert entry["DetailType"] == "tickets"
        assert json.loads(entry["Detail"]) == event

    async def test_key_is_carried_in_the_envelope(self, bus_client):
        await _publisher(bus_client).publish("ocean.tasks", {"event_type": "task.claimed"}, key="task-7")

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        assert json.loads(entry["Detail"])["key"] == "task-7"

    async def test_retired_topic_is_rejected_before_the_bus(self, bus_client):
        with pytest.raises(KeyError):
            await _publisher(bus_client).publish("ocean.warehouse-dlq", {"event_type": "x"})

        bus_client.put_events.assert_not_called()


class TestFailurePath:
    async def test_bus_failure_writes_failed_webhooks(self, bus_client, session_maker):
        bus_client.put_events.side_effect = RuntimeError("bus unavailable")
        event = {"event_type": "ticket.update.requested", "entity_id": "t-1"}

        await _publisher(bus_client, session_maker).publish("ocean.tickets", event, key="t-1")

        statement, params = session_maker.session.execute.call_args.args
        assert "failed_webhooks" in str(statement)
        assert params["key"] == "t-1"
        assert json.loads(params["payload"])["entity_id"] == "t-1"

    async def test_bus_failure_does_not_raise_to_the_caller(self, bus_client, session_maker):
        bus_client.put_events.side_effect = RuntimeError("bus unavailable")

        await _publisher(bus_client, session_maker).publish("ocean.tasks", {"event_type": "task.claimed"})
