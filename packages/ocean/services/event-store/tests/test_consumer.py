"""Tests for event-store consumer module."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # noqa: F401 — used in pytest.raises
from confluent_kafka import KafkaError


SAMPLE_EVENT = {
    "event_id": "evt-001",
    "event_type": "signal.received",
    "schema_version": "1.0.0",
    "entity_type": "patient",
    "entity_id": "pat-001",
    "source_system": "pocar",
    "correlation_id": "corr-001",
    "actor_id": "user-001",
    "timestamp": "2026-03-15T10:00:00Z",
    "payload": {"key": "value"},
}


def _make_message(value: bytes | None = None, topic: str = "ocean.signals", error=None):
    msg = MagicMock()
    msg.value.return_value = value or json.dumps(SAMPLE_EVENT).encode()
    msg.topic.return_value = topic
    msg.partition.return_value = 0
    msg.offset.return_value = 0
    msg.error.return_value = error
    return msg


def _make_consumer(messages: list):
    """Build a mock AIOConsumer that yields messages then raises CancelledError."""
    consumer = AsyncMock()
    consumer.subscribe = AsyncMock()
    consumer.close = AsyncMock()
    consumer.commit = AsyncMock()

    # poll side_effect: iterate through messages, then raise CancelledError
    poll_values = messages + [asyncio.CancelledError()]
    consumer.poll = AsyncMock(side_effect=poll_values)
    return consumer


async def test_consumer_topics_list():
    from src.consumer import TOPICS
    expected = [
        "ocean.signals",
        "ocean.alerts",
        "ocean.tasks",
        "ocean.interactions",
        "ocean.outcomes",
        "ocean.ai-ops",
        "ocean.audit",
        "ocean.logistics",
        "ocean.ops",
    ]
    assert TOPICS == expected


async def test_run_consumer_calls_writer_on_message():
    msg = _make_message()
    mock_consumer = _make_consumer([msg])
    mock_writer = AsyncMock()
    mock_writer.write_event = AsyncMock()

    with patch("src.consumer.Consumer", return_value=mock_consumer):
        from src.consumer import run_consumer
        with pytest.raises(asyncio.CancelledError):
            await run_consumer(mock_writer, "localhost:9092")

    mock_writer.write_event.assert_awaited_once_with(
        msg.value(), topic=msg.topic()
    )


async def test_run_consumer_commits_after_write():
    msg = _make_message()
    mock_consumer = _make_consumer([msg])
    mock_writer = AsyncMock()
    mock_writer.write_event = AsyncMock()

    with patch("src.consumer.Consumer", return_value=mock_consumer):
        from src.consumer import run_consumer
        with pytest.raises(asyncio.CancelledError):
            await run_consumer(mock_writer, "localhost:9092")

    mock_consumer.commit.assert_awaited_once_with(message=msg)


async def test_run_consumer_skips_commit_on_write_failure():
    msg = _make_message()
    mock_consumer = _make_consumer([msg])
    mock_writer = AsyncMock()
    mock_writer.write_event = AsyncMock(side_effect=Exception("db error"))

    with patch("src.consumer.Consumer", return_value=mock_consumer):
        from src.consumer import run_consumer
        with pytest.raises(asyncio.CancelledError):
            await run_consumer(mock_writer, "localhost:9092")

    mock_consumer.commit.assert_not_awaited()


async def test_run_consumer_skips_partition_eof():
    error = MagicMock()
    error.code.return_value = KafkaError._PARTITION_EOF
    msg = _make_message(error=error)
    mock_consumer = _make_consumer([msg])
    mock_writer = AsyncMock()
    mock_writer.write_event = AsyncMock()

    with patch("src.consumer.Consumer", return_value=mock_consumer):
        from src.consumer import run_consumer
        with pytest.raises(asyncio.CancelledError):
            await run_consumer(mock_writer, "localhost:9092")

    mock_writer.write_event.assert_not_awaited()
