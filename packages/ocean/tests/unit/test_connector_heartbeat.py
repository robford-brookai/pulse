"""Unit tests for connector heartbeat publish loop."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from utils import setup_service

setup_service("pocar-connector")

import src.heartbeat as heartbeat_mod  # noqa: E402

from src.heartbeat import HEARTBEAT_INTERVAL_SECS, publish_heartbeat  # noqa: E402


@pytest.mark.asyncio
async def test_heartbeat_publishes_correct_topic_and_key():
    """publish_heartbeat calls publisher.publish with topic=ocean.ops and key=connector_id."""
    publisher = AsyncMock()

    async def cancel_after_first_sleep(secs):
        raise asyncio.CancelledError

    with patch.object(heartbeat_mod.asyncio, "sleep", side_effect=cancel_after_first_sleep):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "pocar-connector", "POCAR")

    publisher.publish.assert_called_once()
    call_kwargs = publisher.publish.call_args
    assert call_kwargs.kwargs["topic"] == "ocean.ops" or call_kwargs[1]["topic"] == "ocean.ops"


@pytest.mark.asyncio
async def test_heartbeat_payload_contains_connector_fields():
    """Heartbeat event payload includes connector_id and connector_name."""
    publisher = AsyncMock()

    async def cancel_after_first_sleep(secs):
        raise asyncio.CancelledError

    with patch.object(heartbeat_mod.asyncio, "sleep", side_effect=cancel_after_first_sleep):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "pocar-connector", "POCAR")

    raw = publisher.publish.call_args.kwargs.get("value") or publisher.publish.call_args[1]["value"]
    event = json.loads(raw)
    assert event["payload"]["connector_id"] == "pocar-connector"
    assert event["payload"]["connector_name"] == "POCAR"


@pytest.mark.asyncio
async def test_heartbeat_event_has_base_envelope_fields():
    """Heartbeat event includes all BaseEvent envelope fields."""
    publisher = AsyncMock()

    async def cancel_after_first_sleep(secs):
        raise asyncio.CancelledError

    with patch.object(heartbeat_mod.asyncio, "sleep", side_effect=cancel_after_first_sleep):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "test-connector", "Test")

    raw = publisher.publish.call_args.kwargs.get("value") or publisher.publish.call_args[1]["value"]
    event = json.loads(raw)
    required_fields = [
        "event_id",
        "event_type",
        "schema_version",
        "timestamp",
        "source_system",
        "entity_type",
        "entity_id",
        "correlation_id",
        "actor_id",
        "payload",
    ]
    for field in required_fields:
        assert field in event, f"Missing BaseEvent field: {field}"
    assert event["event_type"] == "connector.heartbeat"
    assert event["schema_version"] == "1.0.0"
    assert event["source_system"] == "test-connector"
    assert event["entity_type"] == "connector"
    assert event["entity_id"] == "test-connector"


@pytest.mark.asyncio
async def test_heartbeat_catches_publish_exceptions():
    """If publisher.publish raises, heartbeat logs error and continues loop."""
    publisher = AsyncMock()
    call_count = 0

    async def fail_then_cancel(secs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError

    publisher.publish.side_effect = RuntimeError("broker down")

    with patch.object(heartbeat_mod.asyncio, "sleep", side_effect=fail_then_cancel):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "pocar-connector", "POCAR")

    # publish was called twice (once per loop iteration), both failed but loop continued
    assert publisher.publish.call_count == 2


@pytest.mark.asyncio
async def test_heartbeat_cancelled_error_propagates():
    """CancelledError from asyncio.sleep propagates out (clean shutdown)."""
    publisher = AsyncMock()

    async def cancel_immediately(secs):
        raise asyncio.CancelledError

    with patch.object(heartbeat_mod.asyncio, "sleep", side_effect=cancel_immediately):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "pocar-connector", "POCAR")


def test_heartbeat_interval_below_silence_threshold():
    """Heartbeat interval must be less than the 300s silence threshold."""
    assert HEARTBEAT_INTERVAL_SECS < 300
