"""Tests for event-store SQS consumer module.

The consumer polls the event-store SQS queue fed by its EventBridge rule.
Each message body is an EventBridge event: the envelope travels whole in
``detail`` and the domain is ``detail-type``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

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

QUEUE_URL = "http://localhost:4566/000000000000/ocean-event-store"


def _make_sqs_message(
    envelope: dict[str, Any] | None = None,
    detail_type: str = "signals",
    body: str | None = None,
    receipt_handle: str = "rh-001",
) -> dict[str, Any]:
    if body is None:
        body = json.dumps({
            "version": "0",
            "id": "eb-id-001",
            "detail-type": detail_type,
            "source": "ocean",
            "time": "2026-03-15T10:00:01Z",
            "detail": envelope if envelope is not None else SAMPLE_EVENT,
        })
    return {"MessageId": "m-001", "ReceiptHandle": receipt_handle, "Body": body}


def _make_sqs_client(batches: list[list[dict[str, Any]]]) -> AsyncMock:
    """Build a mock SQS client that yields message batches then raises CancelledError."""
    client = AsyncMock()
    responses: list[Any] = [{"Messages": batch} for batch in batches]
    responses.append(asyncio.CancelledError())
    client.receive_message = AsyncMock(side_effect=responses)
    client.delete_message = AsyncMock()
    return client


async def test_run_consumer_writes_envelope_from_detail():
    sqs_client = _make_sqs_client([[_make_sqs_message()]])
    mock_writer = AsyncMock()

    from src.consumer import run_consumer

    with pytest.raises(asyncio.CancelledError):
        await run_consumer(mock_writer, QUEUE_URL, sqs_client=sqs_client)

    mock_writer.write_event.assert_awaited_once()
    event_bytes, kwargs = (
        mock_writer.write_event.await_args.args[0],
        mock_writer.write_event.await_args.kwargs,
    )
    assert json.loads(event_bytes) == SAMPLE_EVENT
    assert kwargs == {"topic": "signals"}


async def test_run_consumer_deletes_after_write():
    msg = _make_sqs_message(receipt_handle="rh-del")
    sqs_client = _make_sqs_client([[msg]])
    mock_writer = AsyncMock()

    from src.consumer import run_consumer

    with pytest.raises(asyncio.CancelledError):
        await run_consumer(mock_writer, QUEUE_URL, sqs_client=sqs_client)

    sqs_client.delete_message.assert_awaited_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-del")


async def test_run_consumer_skips_delete_on_write_failure():
    sqs_client = _make_sqs_client([[_make_sqs_message()]])
    mock_writer = AsyncMock()
    mock_writer.write_event = AsyncMock(side_effect=Exception("db error"))

    from src.consumer import run_consumer

    with pytest.raises(asyncio.CancelledError):
        await run_consumer(mock_writer, QUEUE_URL, sqs_client=sqs_client)

    sqs_client.delete_message.assert_not_awaited()


async def test_run_consumer_leaves_malformed_body_for_redrive():
    sqs_client = _make_sqs_client([[_make_sqs_message(body="not json")]])
    mock_writer = AsyncMock()

    from src.consumer import run_consumer

    with pytest.raises(asyncio.CancelledError):
        await run_consumer(mock_writer, QUEUE_URL, sqs_client=sqs_client)

    mock_writer.write_event.assert_not_awaited()
    sqs_client.delete_message.assert_not_awaited()


async def test_run_consumer_survives_receive_error(monkeypatch):
    good = _make_sqs_message()
    client = AsyncMock()
    client.receive_message = AsyncMock(
        side_effect=[Exception("throttled"), {"Messages": [good]}, asyncio.CancelledError()]
    )
    client.delete_message = AsyncMock()
    mock_writer = AsyncMock()

    monkeypatch.setattr("src.consumer.asyncio.sleep", AsyncMock())

    from src.consumer import run_consumer

    with pytest.raises(asyncio.CancelledError):
        await run_consumer(mock_writer, QUEUE_URL, sqs_client=client)

    mock_writer.write_event.assert_awaited_once()


async def test_out_of_order_delivery_reaches_same_state():
    """Ordering verdict evidence: the store is append-only keyed by event_id,
    so reversed delivery must produce the identical final state."""
    events = [{**SAMPLE_EVENT, "event_id": f"evt-{i:03d}", "timestamp": f"2026-03-15T10:0{i}:00Z"} for i in range(3)]

    async def deliver(ordered_events: list[dict[str, Any]]) -> dict[str, Any]:
        store: dict[str, Any] = {}

        class FakeWriter:
            async def write_event(self, event_bytes: bytes, topic: str = "unknown") -> None:
                event = json.loads(event_bytes)
                # Mirrors writer.py: INSERT ... ON CONFLICT (event_id) DO NOTHING
                store.setdefault(event["event_id"], event)

        sqs_client = _make_sqs_client([
            [_make_sqs_message(envelope=e, receipt_handle=e["event_id"]) for e in ordered_events]
        ])

        from src.consumer import run_consumer

        with pytest.raises(asyncio.CancelledError):
            await run_consumer(FakeWriter(), QUEUE_URL, sqs_client=sqs_client)
        return store

    in_order = await deliver(events)
    reversed_order = await deliver(list(reversed(events)))

    assert in_order == reversed_order
    assert set(in_order) == {"evt-000", "evt-001", "evt-002"}
