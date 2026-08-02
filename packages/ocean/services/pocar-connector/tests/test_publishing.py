"""Tests for pocar-connector's publish sites after the EventBridge conversion (task 4.4).

Two things are asserted here and nowhere else in this service: every publish site emits through
the shared ``ocean_broker`` publisher rather than service-local transport code, and a bus failure
lands in the Postgres ``failed_webhooks`` table instead of raising at the call site.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from ocean_broker import EventBridgePublisher
from ocean_broker.catalog import address_for

SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"


def _make_payload() -> dict:
    return {
        "alert_id": "alert-test-004",
        "patient_id": "pt-abc123",
        "alert_type": "glucose_missing",
        "severity": "urgent",
        "clinic_id": "clinic-1",
        "triggered_at": "2026-03-05T10:00:00Z",
    }


def _sign(payload_bytes: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_webhook_publishes_through_shared_publisher(client, mock_publisher):
    """The webhook route emits an envelope dict to the 'alerts' domain via the shared publisher."""
    body = json.dumps(_make_payload()).encode()
    resp = await client.post(
        "/webhooks/pocar",
        content=body,
        headers={"Content-Type": "application/json", "X-Pocar-Signature": _sign(body, "test_secret")},
    )
    assert resp.status_code == 200

    mock_publisher.publish.assert_awaited_once()
    kwargs = mock_publisher.publish.await_args.kwargs
    assert kwargs["detail_type"] == "alerts"
    assert kwargs["key"] == resp.json()["event_id"]

    # The envelope crosses the bus whole, as a dict — no service-side serialisation, no field
    # promoted out of it.
    envelope = kwargs["event"]
    assert isinstance(envelope, dict)
    assert envelope["event_id"] == resp.json()["event_id"]
    assert envelope["event_type"] != kwargs["detail_type"]


@pytest.mark.asyncio
async def test_heartbeat_publishes_to_the_ops_domain(mock_publisher):
    """The heartbeat loop addresses 'ops' and carries the connector id as the key."""
    from src.heartbeat import publish_heartbeat

    task = asyncio.create_task(publish_heartbeat(mock_publisher, "pocar-connector", "POCAR"))
    for _ in range(50):
        await asyncio.sleep(0)
        if mock_publisher.publish.await_count:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    kwargs = mock_publisher.publish.await_args.kwargs
    assert kwargs["detail_type"] == "ops"
    assert kwargs["key"] == "pocar-connector"
    assert kwargs["event"]["event_type"] == "connector.heartbeat"


def test_both_domains_this_service_publishes_are_live_addresses():
    """'alerts' and 'ops' resolve in the catalog, so neither publish is a dead address."""
    for domain in ("alerts", "ops"):
        assert address_for(domain).detail_type == domain


def test_no_service_local_transport_code_survives():
    """No module under src/ touches a bus client — the shared publisher is the only transport."""
    assert not (SERVICE_SRC / "producer.py").exists(), "service-local transport module still present"
    for module in sorted(SERVICE_SRC.rglob("*.py")):
        source = module.read_text()
        assert "confluent_kafka" not in source, f"{module.name} still imports the Kafka client"
        assert "boto3" not in source, f"{module.name} constructs a bus client directly"


@pytest.mark.asyncio
async def test_bus_failure_writes_failed_webhooks():
    """A rejected publish is written to failed_webhooks and does not raise at the call site."""
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

    await publisher.publish(detail_type="alerts", event={"event_id": "e-1"}, key="e-1")

    session.execute.assert_awaited_once()
    statement, params = session.execute.await_args.args
    assert "failed_webhooks" in str(statement)
    assert params["key"] == "e-1"
    assert "bus unavailable" in params["error"]
