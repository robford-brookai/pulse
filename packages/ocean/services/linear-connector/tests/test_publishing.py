"""Tests for the linear-connector publish site after the EventBridge conversion.

The service no longer owns transport code: every publish goes through the shared
``ocean_broker.EventBridgePublisher``. These tests pin the three things that conversion
has to get right — addressing by domain (not ``event_type``), the envelope crossing whole,
and a bus failure landing in ``failed_webhooks`` instead of raising at the caller.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from ocean_broker import EventBridgePublisher

WEBHOOK_SECRET = "test-linear-secret"

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture()
def _set_env(monkeypatch):
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("OCEAN_EVENT_BUS_NAME", "ocean")


@pytest.fixture()
def bus_client():
    """A stand-in for the boto3 ``events`` client that accepts every entry."""
    client = MagicMock()
    client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
    return client


@pytest.fixture()
def dlq_session_maker():
    """A session maker recording the parameters of every ``failed_webhooks`` insert."""
    recorded: list[dict] = []

    class Session:
        async def execute(self, _statement, params):
            recorded.append(params)

        def begin(self):
            return _NullAsyncContext()

    class _NullAsyncContext:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_):
            return None

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *_):
            return None

    maker = MagicMock(side_effect=lambda: SessionContext())
    maker.recorded = recorded
    return maker


@pytest.fixture()
def publisher(_set_env, bus_client, dlq_session_maker):
    """A real EventBridgePublisher with the bus client and Postgres session mocked out."""
    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        mock_boto3.client.return_value = bus_client
        pub = EventBridgePublisher(region="us-east-1", db_session_maker=dlq_session_maker)
    pub._client = bus_client
    return pub


@pytest.fixture()
def client(publisher):
    from src.main import app

    app.state.publisher = publisher
    return TestClient(app, raise_server_exceptions=False)


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _post_ocean_issue(test_client: TestClient):
    payload = {
        "action": "create",
        "type": "Issue",
        "data": {
            "id": "issue-1",
            "title": "Test issue from Linear",
            "priority": 2,
            "url": "https://linear.app/brook/issue/BROOK-1",
            "labels": [{"name": "ocean"}],
        },
    }
    body = json.dumps(payload).encode()
    return test_client.post(
        "/webhook",
        content=body,
        headers={"linear-signature": _sign(body), "content-type": "application/json"},
    )


class TestSharedPublisher:
    """The site emits through the shared publisher, not its own transport code."""

    def test_no_service_local_bus_client(self):
        """No module under src/ imports a bus client directly."""
        offenders = [
            path.name for path in sorted(SRC_DIR.glob("*.py")) if "confluent_kafka" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_producer_module_is_gone(self):
        """The Redpanda producer wrapper is removed rather than reimplemented."""
        assert not (SRC_DIR / "producer.py").exists()

    def test_lifespan_builds_an_eventbridge_publisher_with_dlq(self, _set_env):
        """Startup wires the shared publisher with a Postgres session maker for the DLQ."""
        from src.main import app

        with TestClient(app) as test_client:
            pub = test_client.app.state.publisher
            assert isinstance(pub, EventBridgePublisher)
            assert pub._db_session_maker is not None


class TestAddressing:
    """Domain addressing, not event_type promotion."""

    def test_webhook_publishes_to_the_tickets_domain(self, client, bus_client):
        resp = _post_ocean_issue(client)

        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        bus_client.put_events.assert_called_once()
        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["Source"] == "ocean"
        assert entry["DetailType"] == "tickets"
        assert entry["EventBusName"] == "ocean"

    def test_event_type_is_not_promoted_to_detail_type(self, client, bus_client):
        _post_ocean_issue(client)

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        detail = json.loads(entry["Detail"])
        assert detail["event_type"].startswith("ticket.")
        assert entry["DetailType"] != detail["event_type"]

    def test_envelope_crosses_whole(self, client, bus_client):
        _post_ocean_issue(client)

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        detail = json.loads(entry["Detail"])
        from src.normalizer import normalize_issue

        expected = normalize_issue(
            {
                "id": "issue-1",
                "title": "Test issue from Linear",
                "priority": 2,
                "url": "https://linear.app/brook/issue/BROOK-1",
                "labels": [{"name": "ocean"}],
            },
            "create",
        )
        assert expected is not None
        # event_id, correlation_id and timestamp are generated per call; the rest must match.
        volatile = {"event_id", "correlation_id", "timestamp"}
        assert set(detail) == set(expected)
        assert {k: v for k, v in detail.items() if k not in volatile} == {
            k: v for k, v in expected.items() if k not in volatile
        }

    @pytest.mark.asyncio
    async def test_heartbeat_publishes_to_the_ops_domain(self, publisher, bus_client):
        from src.heartbeat import publish_heartbeat

        with patch("src.heartbeat.asyncio.sleep", side_effect=StopAsyncIteration):
            with pytest.raises(StopAsyncIteration):
                await publish_heartbeat(publisher, "linear-connector", "Linear Issue Tracker")

        entry = bus_client.put_events.call_args.kwargs["Entries"][0]
        assert entry["DetailType"] == "ops"
        assert json.loads(entry["Detail"])["event_type"] == "connector.heartbeat"


class TestFailurePath:
    """A bus failure dead-letters to Postgres and never reaches the caller."""

    def test_bus_failure_writes_failed_webhooks(self, client, bus_client, dlq_session_maker):
        bus_client.put_events.side_effect = RuntimeError("bus unavailable")

        resp = _post_ocean_issue(client)

        assert resp.status_code == 200
        assert len(dlq_session_maker.recorded) == 1
        row = dlq_session_maker.recorded[0]
        assert "bus unavailable" in row["error"]
        dead_lettered = json.loads(row["payload"])
        assert dead_lettered["event_type"] == "ticket.create.requested"
        assert dead_lettered["payload"]["source_url"] == "https://linear.app/brook/issue/BROOK-1"

    def test_rejected_entry_writes_failed_webhooks(self, client, bus_client, dlq_session_maker):
        bus_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorMessage": "ThrottlingException"}],
        }

        resp = _post_ocean_issue(client)

        assert resp.status_code == 200
        assert len(dlq_session_maker.recorded) == 1
        assert dlq_session_maker.recorded[0]["error"] == "ThrottlingException"
