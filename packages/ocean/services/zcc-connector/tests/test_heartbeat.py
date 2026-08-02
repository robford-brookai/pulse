"""Unit tests for ZCC connector heartbeat background task."""
from __future__ import annotations

import asyncio
import json
import sys
import os
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.mark.asyncio
async def test_publish_heartbeat_calls_publisher_with_correct_args():
    """publish_heartbeat calls publisher.publish with topic=ocean.ops, key=zcc-connector, and heartbeat event."""
    from src.heartbeat import publish_heartbeat

    publisher = AsyncMock()
    call_count = 0

    async def publish_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError()

    publisher.publish = AsyncMock(side_effect=publish_side_effect)

    with pytest.raises(asyncio.CancelledError):
        await publish_heartbeat(publisher, "zcc-connector", "Zoom Contact Center")

    publisher.publish.assert_called_once()
    call_kwargs = publisher.publish.call_args[1]
    assert call_kwargs["topic"] == "ocean.ops"
    assert call_kwargs["key"] == "zcc-connector"
    event = json.loads(call_kwargs["value"])
    assert event["event_type"] == "connector.heartbeat"
    assert event["source_system"] == "zcc-connector"
    assert event["payload"]["connector_name"] == "Zoom Contact Center"


@pytest.mark.asyncio
async def test_publish_heartbeat_catches_publisher_exceptions():
    """Publisher exceptions are caught and logged without crashing the loop."""
    from src.heartbeat import publish_heartbeat

    publisher = AsyncMock()
    call_count = 0

    async def publish_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("broker down")
        # Second call succeeds then we cancel
        raise asyncio.CancelledError()

    publisher.publish = AsyncMock(side_effect=publish_side_effect)

    with patch("src.heartbeat.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "zcc-connector", "Zoom Contact Center")

    # Loop continued past the ConnectionError to make a second call
    assert publisher.publish.call_count == 2


@pytest.mark.asyncio
async def test_publish_heartbeat_propagates_cancelled_error():
    """CancelledError from asyncio.sleep propagates for clean shutdown."""
    from src.heartbeat import publish_heartbeat

    publisher = AsyncMock()

    with patch("src.heartbeat.asyncio.sleep", side_effect=asyncio.CancelledError()):
        with pytest.raises(asyncio.CancelledError):
            await publish_heartbeat(publisher, "zcc-connector", "Zoom Contact Center")

    # publish was called once before sleep raised CancelledError
    assert publisher.publish.call_count == 1
