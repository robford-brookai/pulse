"""The connector publishes through the shared EventBridge publisher, not a local transport.

Task 4.3 (DNA-746) converts this service's publish site. What these tests pin down is the
contract from `event-transport`: every site emits through `ocean_broker.EventBridgePublisher`,
the domain is the `detail-type` (never the envelope's `event_type`), the key rides as an
envelope field, and a bus failure lands in `failed_webhooks` instead of raising.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from ocean_broker import EventBridgePublisher
from src.heartbeat import publish_heartbeat
from src.sqs_consumer import sqs_consumer_loop

READING_PAYLOAD = {
    "type": "reading.weight",
    "id": 456,
    "patient": {"id": 123},
    "value": 185.5,
    "unit": "lbs",
    "createdAt": "2026-03-06T10:00:00Z",
}

_SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"


class TestSharedPublisherIsTheOnlyTransport:
    """No service-local transport code survives the conversion."""

    def test_no_source_file_references_a_bus_client(self) -> None:
        offenders = [
            path.name
            for path in sorted(_SERVICE_SRC.glob("*.py"))
            if "confluent_kafka" in path.read_text() or "RedpandaPublisher" in path.read_text()
        ]
        assert offenders == []

    def test_producer_module_is_gone(self) -> None:
        assert not (_SERVICE_SRC / "producer.py").exists()

    async def test_lifespan_wires_the_shared_publisher(self, monkeypatch) -> None:
        import src.main as main

        constructed = {}

        def fake_publisher(**kwargs):
            constructed.update(kwargs)
            return AsyncMock()

        monkeypatch.setattr(main, "EventBridgePublisher", fake_publisher)
        monkeypatch.setattr(main, "create_async_engine", MagicMock(return_value=AsyncMock()))
        monkeypatch.delenv("SQS_QUEUE_URL", raising=False)

        async with main.lifespan(main.app):
            assert isinstance(main.app.state.publisher, AsyncMock)

        assert "db_session_maker" in constructed


class TestDomainIsTheDetailType:
    """`detail-type` is the domain; `event_type` stays an envelope field."""

    async def test_receiver_publishes_the_domain_not_the_event_type(self, client, mock_publisher) -> None:
        resp = await client.post(
            "/webhooks/impilo",
            content=json.dumps(READING_PAYLOAD),
            headers={"Impilo-API-Key": "test_impilo_key", "Content-Type": "application/json"},
        )
        assert resp.status_code == 200

        kwargs = mock_publisher.publish.await_args.kwargs
        assert kwargs["detail_type"] == "signals"
        assert kwargs["event"]["event_type"] == "signal.received"
        assert kwargs["key"] == resp.json()["event_id"]

    async def test_receiver_passes_the_envelope_whole(self, client, mock_publisher) -> None:
        await client.post(
            "/webhooks/impilo",
            content=json.dumps(READING_PAYLOAD),
            headers={"Impilo-API-Key": "test_impilo_key", "Content-Type": "application/json"},
        )

        event = mock_publisher.publish.await_args.kwargs["event"]
        assert isinstance(event, dict)
        # Not pre-serialised: the shared publisher owns the JSON encoding.
        assert {"event_id", "event_type", "schema_version", "payload"} <= set(event)

    async def test_heartbeat_publishes_to_the_ops_domain(self, mock_publisher, monkeypatch) -> None:
        monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(mock_publisher, "impilo-connector", "Impilo RPM")

        kwargs = mock_publisher.publish.await_args.kwargs
        assert kwargs["detail_type"] == "ops"
        assert kwargs["event"]["event_type"] == "connector.heartbeat"
        assert kwargs["key"] == "impilo-connector"

    async def test_sqs_consumer_publishes_the_domain(self, mock_publisher) -> None:
        message = {
            "Body": json.dumps({"Type": "Notification", "Message": json.dumps(READING_PAYLOAD)}),
            "ReceiptHandle": "rh-1",
        }
        sqs_client = AsyncMock()
        sqs_client.receive_message = AsyncMock(side_effect=[{"Messages": [message]}, asyncio.CancelledError()])

        with pytest.raises(asyncio.CancelledError):
            await sqs_consumer_loop(mock_publisher, "https://sqs.test/q", sqs_client=sqs_client)

        kwargs = mock_publisher.publish.await_args.kwargs
        assert kwargs["detail_type"] == "signals"
        assert kwargs["event"]["event_type"] == "signal.received"


class TestPublishFailureFallsBackToFailedWebhooks:
    """The DLQ fallback this connector had under Kafka survives the transport change."""

    async def test_bus_failure_writes_failed_webhooks_and_does_not_raise(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)
        session.begin = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
        )
        session_maker = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock(return_value=False))
        )

        publisher = EventBridgePublisher(region="us-east-1", db_session_maker=session_maker)
        publisher._client = MagicMock()
        publisher._client.put_events = MagicMock(side_effect=RuntimeError("bus unavailable"))

        await publisher.publish("signals", {"event_id": "e-1", "event_type": "signal.received"}, key="e-1")

        statement, params = session.execute.await_args.args
        assert "failed_webhooks" in str(statement)
        assert params["key"] == "e-1"
        assert json.loads(params["payload"])["event_type"] == "signal.received"
