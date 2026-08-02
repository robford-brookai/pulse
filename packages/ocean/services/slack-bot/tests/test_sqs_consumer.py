"""Tests for the slack-bot SQS receive/process/delete loop (5.6, DNA-762).

The loop must preserve the Kafka consumer's commit-after-success semantics:
a message is deleted only after its handler returns, a failed handler leaves
the message for visibility-timeout redelivery, and ``ParentMessageNotReady``
(the 3.5 sequence-guard signal) is a redelivery, not a drop.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
import src.consumer as consumer_mod
from src.consumer import ParentMessageNotReady, run_consumer

QUEUE_URL = "https://sqs.test/slack-bot"


def _envelope(event_type: str = "task.claimed", entity_id: str = "task-001") -> dict:
    return {
        "event_id": "evt-001",
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": "2026-03-08T12:00:00Z",
        "source_system": "control-plane",
        "entity_type": "task",
        "entity_id": entity_id,
        "correlation_id": "corr-001",
        "actor_id": None,
        "payload": {"task_id": entity_id, "persona_id": "coordinator_alice"},
    }


def _eventbridge_sqs_message(envelope: dict, receipt_handle: str = "rh-1") -> dict:
    """Build the SQS message an EventBridge rule delivers: envelope inside ``detail``."""
    body = {
        "version": "0",
        "id": "eb-msg-001",
        "detail-type": "tasks",
        "source": "ocean",
        "account": "000000000000",
        "time": "2026-03-08T12:00:00Z",
        "region": "us-east-1",
        "detail": envelope,
    }
    return {"Body": json.dumps(body), "ReceiptHandle": receipt_handle}


def _sqs_client(*receive_results: dict) -> Mock:
    """Sync boto3-shaped SQS client: yields each receive result, then cancels the loop."""
    client = Mock()
    client.receive_message = Mock(side_effect=[*receive_results, asyncio.CancelledError()])
    client.delete_message = Mock()
    return client


async def _run(client: Mock, **kwargs) -> None:
    slack_client = kwargs.pop("slack_client", AsyncMock())
    session_maker = kwargs.pop("session_maker", None)
    with pytest.raises(asyncio.CancelledError):
        await run_consumer(
            slack_client,
            session_maker,
            QUEUE_URL,
            "http://hasura.test",
            sqs_client=client,
            **kwargs,
        )


class TestSqsLoop:
    """run_consumer polls SQS, unwraps the EventBridge body, deletes only after success."""

    async def test_unwraps_detail_and_dispatches_to_handler(self):
        envelope = _envelope("task.claimed")
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope)]})
        handler = AsyncMock()

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": handler}):
            await _run(client)

        handler.assert_awaited_once()
        assert handler.await_args[0][0] == envelope

    async def test_handler_receives_wiring_kwargs(self):
        envelope = _envelope("task.claimed")
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope)]})
        handler = AsyncMock()
        slack_client = AsyncMock()
        publisher = AsyncMock()
        thread_manager = AsyncMock()

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": handler}):
            await _run(
                client,
                slack_client=slack_client,
                publisher=publisher,
                thread_manager=thread_manager,
            )

        kwargs = handler.await_args.kwargs
        assert kwargs["slack_client"] is slack_client
        assert kwargs["publisher"] is publisher
        assert kwargs["thread_manager"] is thread_manager
        assert kwargs["hasura_url"] == "http://hasura.test"
        assert "session_maker" in kwargs

    async def test_deletes_after_successful_processing(self):
        envelope = _envelope("task.claimed")
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope, receipt_handle="rh-ok")]})

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": AsyncMock()}):
            await _run(client)

        client.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-ok")

    async def test_handler_failure_leaves_message_for_redelivery(self):
        envelope = _envelope("task.claimed")
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope)]})
        handler = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": handler}):
            await _run(client)

        client.delete_message.assert_not_called()

    async def test_parent_not_ready_leaves_message_for_redelivery(self):
        """The 3.5 guard: an update that overtakes its create is redelivered, not dropped."""
        envelope = _envelope("ticket.updated", entity_id="tkt-001")
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope)]})
        handler = AsyncMock(side_effect=ParentMessageNotReady("no parent yet"))

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"ticket.updated": handler}):
            await _run(client)

        client.delete_message.assert_not_called()

    async def test_unhandled_event_type_is_deleted(self):
        """No handler == the Kafka loop's skip-and-commit: consume and delete."""
        envelope = _envelope("some.unknown.event")
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope, receipt_handle="rh-skip")]})

        await _run(client)

        client.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-skip")

    async def test_malformed_body_not_deleted(self):
        """Poison messages ride redelivery into the queue's DLQ, keeping them inspectable."""
        client = _sqs_client({"Messages": [{"Body": "not json{{{", "ReceiptHandle": "rh-bad"}]})
        handler = AsyncMock()

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": handler}):
            await _run(client)

        handler.assert_not_awaited()
        client.delete_message.assert_not_called()

    async def test_bare_envelope_without_detail_is_accepted(self):
        """Local tooling can send straight to the queue without EventBridge framing."""
        envelope = _envelope("task.claimed")
        client = _sqs_client({"Messages": [{"Body": json.dumps(envelope), "ReceiptHandle": "rh-2"}]})
        handler = AsyncMock()

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": handler}):
            await _run(client)

        assert handler.await_args[0][0] == envelope

    async def test_empty_receive_continues_polling(self):
        client = _sqs_client({}, {"Messages": []})

        await _run(client)

        assert client.receive_message.call_count == 3

    async def test_receive_error_backs_off_and_continues(self):
        client = Mock()
        client.receive_message = Mock(
            side_effect=[RuntimeError("throttled"), {"Messages": []}, asyncio.CancelledError()]
        )
        client.delete_message = Mock()

        with patch.object(consumer_mod, "SQS_ERROR_BACKOFF_SECONDS", 0):
            await _run(client)

        assert client.receive_message.call_count == 3

    async def test_one_failure_does_not_block_the_batch(self):
        """A failed message is skipped; the rest of the batch still processes and deletes."""
        bad = _eventbridge_sqs_message(_envelope("task.claimed", entity_id="task-bad"), receipt_handle="rh-bad")
        good = _eventbridge_sqs_message(_envelope("task.claimed", entity_id="task-good"), receipt_handle="rh-good")
        client = _sqs_client({"Messages": [bad, good]})

        async def handler(event_data, **kwargs):
            if event_data["entity_id"] == "task-bad":
                raise RuntimeError("boom")

        with patch.dict(consumer_mod.EVENT_HANDLERS, {"task.claimed": handler}):
            await _run(client)

        client.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-good")
