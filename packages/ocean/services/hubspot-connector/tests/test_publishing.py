"""Tests for the HubSpot connector's publish path on EventBridge.

The connector keeps no transport code of its own: every publish goes through
``ocean_broker.EventBridgePublisher``. These tests drive the real publisher with a mocked
boto3 client, so the service's side of the contract — domain, envelope, key, DLQ fallback —
is exercised end to end from the webhook route.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from ocean_broker import EventBridgePublisher

CLIENT_SECRET = "test-hubspot-secret"

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _sign(method: str, url: str, body: bytes, timestamp: str) -> str:
    """Compute HubSpot v3 signature: SHA256(secret + method + url + body + timestamp)."""
    source = CLIENT_SECRET + method + url + body.decode("utf-8") + timestamp
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _mock_session_maker() -> MagicMock:
    """An ``async_sessionmaker`` stand-in exposing the session as ``_test_session``."""
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

    maker = MagicMock(side_effect=lambda: SessionContextManager())
    maker._test_session = session
    return maker


@pytest.fixture()
def _set_env(monkeypatch):
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("OCEAN_EVENT_BUS_NAME", "ocean")


@pytest.fixture()
def bus_client() -> MagicMock:
    """Mocked EventBridge client that accepts every entry."""
    client = MagicMock()
    client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
    return client


@pytest.fixture()
def session_maker() -> MagicMock:
    return _mock_session_maker()


@pytest.fixture()
def publisher(_set_env, bus_client, session_maker) -> EventBridgePublisher:
    """A real EventBridgePublisher wired to the mocked bus and DLQ."""
    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        mock_boto3.client.return_value = bus_client
        pub = EventBridgePublisher(region="us-east-1", db_session_maker=session_maker)
    pub._client = bus_client
    return pub


@pytest.fixture()
def client(publisher):
    """TestClient whose app publishes through the shared EventBridge publisher."""
    from src.main import app

    app.state.publisher = publisher
    return TestClient(app, raise_server_exceptions=False)


def _post_contact_creation(test_client: TestClient) -> None:
    """Post one signed ``contact.creation`` webhook."""
    body = json.dumps([{"subscriptionType": "contact.creation", "objectId": 12345, "changeSource": "CRM"}]).encode()
    ts = str(int(time.time()))
    url = "http://testserver/webhook"
    resp = test_client.post(
        "/webhook",
        content=body,
        headers={
            "x-hubspot-signature-v3": _sign("POST", url, body, ts),
            "x-hubspot-request-timestamp": ts,
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted", "count": 1}


class TestWebhookPublishesToEventBridge:
    def test_signal_addresses_to_the_signals_domain(self, client, bus_client):
        """The former ``ocean.signals`` topic becomes source ``ocean`` / detail-type ``signals``."""
        _post_contact_creation(client)

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["Source"] == "ocean"
        assert entry["DetailType"] == "signals"
        assert entry["EventBusName"] == "ocean"

    def test_event_type_is_not_promoted_to_detail_type(self, client, bus_client):
        """``event_type`` stays an envelope field; the detail-type is the domain."""
        entry = None
        _post_contact_creation(client)
        entry = bus_client.put_events.call_args.kwargs["Entries"][0]

        envelope = json.loads(entry["Detail"])
        assert envelope["event_type"] == "contact.created"
        assert entry["DetailType"] != envelope["event_type"]

    def test_envelope_travels_whole_with_the_key_carried(self, client, bus_client):
        """The normalizer's envelope crosses the bus unmodified, plus the grouping key."""
        _post_contact_creation(client)

        envelope = json.loads(bus_client.put_events.call_args.kwargs["Entries"][0]["Detail"])
        assert envelope["source_system"] == "hubspot"
        assert envelope["entity_type"] == "contact"
        assert envelope["entity_id"] == "12345"
        assert envelope["schema_version"] == "1.0.0"
        assert envelope["payload"]["hubspot_contact_id"] == "12345"
        # The key no longer selects a partition; it rides in the envelope for sequence guards.
        assert envelope["key"] == envelope["entity_id"]

    def test_unsupported_subscription_type_publishes_nothing(self, client, bus_client):
        body = json.dumps([{"subscriptionType": "deal.creation", "objectId": 999}]).encode()
        ts = str(int(time.time()))
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "x-hubspot-signature-v3": _sign("POST", "http://testserver/webhook", body, ts),
                "x-hubspot-request-timestamp": ts,
                "content-type": "application/json",
            },
        )

        assert resp.json() == {"status": "skipped"}
        bus_client.put_events.assert_not_called()


class TestPublishFailureFallsBackToPostgres:
    def test_bus_failure_writes_failed_webhooks_and_does_not_raise(self, client, bus_client, session_maker):
        """A bus outage dead-letters the envelope; the webhook still returns 200."""
        bus_client.put_events.side_effect = RuntimeError("bus unavailable")

        _post_contact_creation(client)

        execute = session_maker._test_session.execute
        execute.assert_awaited_once()
        statement, params = execute.await_args.args
        assert "failed_webhooks" in str(statement)
        assert params["key"] == "12345"
        assert json.loads(params["payload"].decode())["event_type"] == "contact.created"
        assert "bus unavailable" in params["error"]

    def test_rejected_entry_writes_failed_webhooks(self, client, bus_client, session_maker):
        """PutEvents reports per-entry rejection in the response rather than by raising."""
        bus_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorMessage": "ThrottlingException"}],
        }

        _post_contact_creation(client)

        params = session_maker._test_session.execute.await_args.args[1]
        assert "ThrottlingException" in params["error"]


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_addresses_to_the_ops_domain(self, publisher, bus_client):
        """The former ``ocean.ops`` topic addresses as detail-type ``ops``."""
        from src.heartbeat import publish_heartbeat

        with patch("src.heartbeat.asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await publish_heartbeat(publisher, "hubspot-connector", "HubSpot Contact Lifecycle")

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["DetailType"] == "ops"
        envelope = json.loads(entry["Detail"])
        assert envelope["event_type"] == "connector.heartbeat"
        assert envelope["key"] == "hubspot-connector"


class TestNoServiceLocalTransportCode:
    def test_no_source_file_references_a_bus_client(self):
        """Per event-transport: transport code lives only in the shared publisher library."""
        offenders = [
            path.name
            for path in sorted(SRC_DIR.glob("*.py"))
            if any(token in path.read_text() for token in ("confluent_kafka", "AIOProducer", "boto3"))
        ]
        assert offenders == []

    def test_service_local_producer_module_is_gone(self):
        assert not (SRC_DIR / "producer.py").exists()
