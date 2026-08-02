"""Tests for the ZCC connector's publisher wiring.

Two things are asserted here, both from the wave 2b contract: the connector emits through the
shared ``ocean_broker`` publisher rather than any transport code of its own, and a bus failure
lands the envelope in ``failed_webhooks`` instead of dropping it.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ocean_broker import EventBridgePublisher

from src import producer

DB_URL = "postgresql+asyncpg://ocean@localhost:5432/ocean"


@pytest.fixture
def fake_session_maker():
    """Session maker whose session records every ``execute`` call."""
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


def test_build_publisher_returns_the_shared_publisher(fake_session_maker):
    """The connector publishes through ocean_broker, not a service-local implementation."""
    with patch("ocean_broker.publisher.boto3"):
        publisher = producer.build_publisher(db_session_maker=fake_session_maker)

    assert isinstance(publisher, EventBridgePublisher)


def test_build_publisher_wires_the_dlq_from_database_url(monkeypatch):
    """Without an injected session maker, the fallback is wired from DATABASE_URL."""
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    captured: dict = {}

    class RecordingPublisher:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(producer, "EventBridgePublisher", RecordingPublisher)
    producer.build_publisher()

    assert captured["db_session_maker"] is not None


def test_missing_database_url_fails_at_startup(monkeypatch):
    """The fallback is not optional: no DATABASE_URL is a startup error, not a silent drop."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(KeyError):
        producer.build_publisher()


@pytest.mark.asyncio
async def test_bus_failure_writes_failed_webhooks(fake_session_maker):
    """A rejected publish writes the envelope to failed_webhooks and does not raise."""
    client = MagicMock()
    client.put_events = MagicMock(side_effect=RuntimeError("bus unavailable"))

    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        mock_boto3.client.return_value = client
        publisher = producer.build_publisher(db_session_maker=fake_session_maker)

    envelope = {"event_type": "call.completed", "entity_id": "eng-test-001"}
    await publisher.publish(detail_type="interactions", event=envelope, key="eng-test-001")

    fake_session_maker._test_session.execute.assert_awaited_once()
    statement, params = fake_session_maker._test_session.execute.await_args.args
    assert "INSERT INTO failed_webhooks" in str(statement)
    assert params["key"] == "eng-test-001"
    assert json.loads(params["payload"])["event_type"] == "call.completed"
    assert "bus unavailable" in params["error"]


def test_no_service_local_transport_code_survives():
    """No Kafka client and no service-local publisher class remain in this module."""
    source = inspect.getsource(producer)

    assert "confluent_kafka" not in source
    assert not hasattr(producer, "RedpandaPublisher")
