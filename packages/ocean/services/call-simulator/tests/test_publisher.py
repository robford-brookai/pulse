"""Tests for call-simulator's publisher wiring.

call-simulator holds no transport code of its own: it builds the shared
``EventBridgePublisher`` and names the domain it emits to. These tests pin both,
plus the ``failed_webhooks`` fallback the service gains by inheritance.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ocean_broker import EventBridgePublisher
from src.publisher import DOMAIN, build_dlq_session_maker, build_publisher


def _fake_session_maker():
    """A session maker whose session records the statements executed against it."""
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


class TestDomain:
    def test_domain_is_the_live_interactions_domain(self):
        """The former ``ocean.interactions`` topic addresses as the ``interactions`` domain."""
        from ocean_broker import address_for

        assert DOMAIN == "interactions"
        assert address_for(DOMAIN).kafka_topic == "ocean.interactions"


class TestBuildPublisher:
    def test_returns_the_shared_publisher(self):
        with patch("ocean_broker.publisher.boto3"):
            publisher = build_publisher()

        assert isinstance(publisher, EventBridgePublisher)

    def test_dlq_session_maker_absent_without_a_database_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)

        assert build_dlq_session_maker() is None

    def test_dlq_session_maker_built_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ocean:pw@postgres:5432/ocean")

        with patch("src.publisher.create_async_engine") as mock_engine:
            maker = build_dlq_session_maker()

        assert maker is not None
        mock_engine.assert_called_once()

    def test_publisher_carries_the_dlq_session_maker(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ocean:pw@postgres:5432/ocean")

        with patch("ocean_broker.publisher.boto3"), patch("src.publisher.create_async_engine"):
            publisher = build_publisher()

        assert publisher._db_session_maker is not None


class TestNoServiceLocalTransport:
    def test_no_bus_client_import_survives_in_the_service(self):
        """No source file outside the shared publisher library touches a bus client."""
        src_dir = Path(__file__).resolve().parents[1] / "src"
        offenders = [
            path.name
            for path in sorted(src_dir.glob("*.py"))
            # consumer.py converts in task 5.3 and still holds the Kafka consumer.
            if path.name != "consumer.py" and "confluent_kafka" in path.read_text()
        ]

        assert offenders == []


class TestPublishFailureFallback:
    async def test_bus_failure_writes_failed_webhooks(self):
        """A bus rejection is captured in ``failed_webhooks``; the caller does not raise."""
        maker = _fake_session_maker()
        client = MagicMock()
        client.put_events = MagicMock(side_effect=RuntimeError("bus unavailable"))

        with patch("ocean_broker.publisher.boto3"):
            publisher = EventBridgePublisher(region="us-east-1", db_session_maker=maker)
        publisher._client = client

        envelope = {"event_type": "call.started", "entity_id": "int-001"}
        await publisher.publish(DOMAIN, envelope)

        maker._test_session.execute.assert_awaited_once()
        params = maker._test_session.execute.await_args.args[1]
        assert json.loads(params["payload"]) == envelope
        assert "bus unavailable" in params["error"]
