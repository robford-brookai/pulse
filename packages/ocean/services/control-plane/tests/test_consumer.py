"""Unit tests for the control-plane SQS consumer loop (task 5.4, DNA-760).

Covers the receive → process → delete contract from the event-delivery spec:
- a message is deleted only after its handler transaction commits
- a failed dispatch leaves the message for visibility-timeout redelivery
- a malformed body is left for redelivery (the queue's redrive policy dead-letters it)
- the envelope travels whole in EventBridge ``detail``; a bare envelope is accepted
- one session transaction per message, publisher forwarded to dispatch
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src import consumer

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/ocean-control-plane"


def _sqs_message(envelope: dict, receipt: str = "rh-1", *, wrap_detail: bool = True) -> dict:
    body: dict = {"detail": envelope, "detail-type": "alerts", "source": "ocean"} if wrap_detail else envelope
    return {"Body": json.dumps(body), "ReceiptHandle": receipt}


class _StopLoop(BaseException):
    """Ends the infinite consumer loop.

    A ``BaseException`` on purpose: the loop's receive path catches ``Exception``
    as a transient SQS failure and retries after a backoff, which would swallow
    a plain ``Exception`` sentinel and hang the test.
    """


class FakeSQSClient:
    """Blocking-style SQS double: one batch of messages, then loop exit."""

    def __init__(self, messages: list[dict]) -> None:
        self._batches = [messages]
        self.deleted: list[str] = []

    def receive_message(self, **kwargs: object) -> dict:
        if not self._batches:
            raise _StopLoop
        return {"Messages": self._batches.pop(0)}

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        self.deleted.append(ReceiptHandle)


def _session_maker() -> MagicMock:
    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.begin = MagicMock(return_value=begin_ctx)

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=session_ctx)


async def _run(client: FakeSQSClient, session_maker: MagicMock, publisher: object = None) -> None:
    with pytest.raises(_StopLoop):
        await consumer.run_consumer(session_maker, QUEUE_URL, publisher=publisher, sqs_client=client)


class TestReceiveProcessDelete:
    @pytest.mark.asyncio
    async def test_successful_dispatch_deletes_message(self):
        envelope = {"event_type": "alert.created", "entity_id": "e-1"}
        client = FakeSQSClient([_sqs_message(envelope)])

        with patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            await _run(client, _session_maker())

        assert mock_dispatch.await_count == 1
        assert client.deleted == ["rh-1"]

    @pytest.mark.asyncio
    async def test_failed_dispatch_leaves_message_for_redelivery(self):
        envelope = {"event_type": "alert.created", "entity_id": "e-1"}
        client = FakeSQSClient([_sqs_message(envelope)])

        with patch("src.consumer.dispatch", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            await _run(client, _session_maker())

        assert client.deleted == []

    @pytest.mark.asyncio
    async def test_malformed_body_is_left_for_redelivery(self):
        client = FakeSQSClient([{"Body": "not json{", "ReceiptHandle": "rh-bad"}])

        with patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            await _run(client, _session_maker())

        assert mock_dispatch.await_count == 0
        assert client.deleted == []

    @pytest.mark.asyncio
    async def test_non_dict_body_is_left_for_redelivery(self):
        client = FakeSQSClient([{"Body": json.dumps([1, 2]), "ReceiptHandle": "rh-list"}])

        with patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            await _run(client, _session_maker())

        assert mock_dispatch.await_count == 0
        assert client.deleted == []

    @pytest.mark.asyncio
    async def test_failure_does_not_block_later_messages_in_batch(self):
        good = {"event_type": "alert.created", "entity_id": "e-2"}
        client = FakeSQSClient([
            _sqs_message({"event_type": "alert.created", "entity_id": "e-1"}, "rh-fail"),
            _sqs_message(good, "rh-ok"),
        ])
        calls = 0

        async def flaky(event_data, session, producer=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")

        with patch("src.consumer.dispatch", side_effect=flaky):
            await _run(client, _session_maker())

        assert client.deleted == ["rh-ok"]


class TestEnvelopeExtraction:
    @pytest.mark.asyncio
    async def test_envelope_travels_whole_in_detail(self):
        envelope = {"event_type": "ticket.create.requested", "payload": {"title": "t"}}
        client = FakeSQSClient([_sqs_message(envelope)])

        with patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            await _run(client, _session_maker())

        dispatched = mock_dispatch.call_args[0][0]
        assert dispatched == envelope

    @pytest.mark.asyncio
    async def test_bare_envelope_is_accepted(self):
        envelope = {"event_type": "alert.created", "entity_id": "e-1"}
        client = FakeSQSClient([_sqs_message(envelope, wrap_detail=False)])

        with patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            await _run(client, _session_maker())

        assert mock_dispatch.call_args[0][0] == envelope
        assert client.deleted == ["rh-1"]


class TestTransactionAndPublisher:
    @pytest.mark.asyncio
    async def test_one_transaction_per_message_and_publisher_forwarded(self):
        envelope = {"event_type": "alert.created", "entity_id": "e-1"}
        client = FakeSQSClient([_sqs_message(envelope)])
        session_maker = _session_maker()
        publisher = AsyncMock()

        with patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            await _run(client, session_maker, publisher=publisher)

        session_maker.assert_called_once()
        assert mock_dispatch.call_args.kwargs.get("producer") is publisher

    @pytest.mark.asyncio
    async def test_unknown_event_type_is_deleted_not_redelivered(self):
        """dispatch() skips unknown types without raising, so the message is acknowledged."""
        envelope = {"event_type": "totally.unknown"}
        client = FakeSQSClient([_sqs_message(envelope)])

        await _run(client, _session_maker())

        assert client.deleted == ["rh-1"]


class TestNoKafkaResidue:
    def test_consumer_module_has_no_kafka_reference(self):
        src_path = os.path.join(os.path.dirname(__file__), "..", "src", "consumer.py")
        with open(src_path) as f:
            source = f.read()
        assert "confluent_kafka" not in source
        assert "bootstrap" not in source
