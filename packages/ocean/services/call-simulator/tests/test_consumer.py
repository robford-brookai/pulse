"""Tests for call-simulator's SQS consumer.

Ordering verdict under test (design D3): **order-tolerant** — one domain, one independent
dispatch per approval event, no cross-event lifecycle state. The out-of-order test below is
the evidence: reversed delivery dispatches the same set of simulations as in-order delivery.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import src.consumer as consumer_module
from src.consumer import DOMAIN, FILTER_EVENT_TYPE, AIOConsumer


def approval_envelope(event_id: str = "evt-1") -> dict:
    return {
        "event_id": event_id,
        "event_type": FILTER_EVENT_TYPE,
        "schema_version": "1.0.0",
        "correlation_id": f"corr-{event_id}",
        "payload": {
            "patient_id": "sim-patient-1",
            "persona_id": "persona-1",
            "call_answer_rate": 1.0,
        },
    }


def sqs_message(envelope: dict, receipt_handle: str = "rh-1") -> dict:
    """An SQS message as EventBridge delivers it: the envelope whole inside ``detail``."""
    body = {
        "version": "0",
        "id": "eb-id",
        "source": "ocean",
        "detail-type": DOMAIN,
        "detail": envelope,
    }
    return {"Body": json.dumps(body), "ReceiptHandle": receipt_handle}


class FakeSQSClient:
    """Synchronous stand-in for boto3's SQS client.

    Serves each batch once; when drained it stops the consumer so ``start()``
    returns instead of long-polling forever.
    """

    def __init__(self, batches: list[list[dict]]) -> None:
        self._batches = list(batches)
        self.deleted: list[str] = []
        self.receive_calls: list[dict] = []
        self.on_drained = lambda: None

    def receive_message(self, **kwargs) -> dict:
        self.receive_calls.append(kwargs)
        if not self._batches:
            self.on_drained()
            return {}
        return {"Messages": self._batches.pop(0)}

    def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> None:
        self.deleted.append(ReceiptHandle)


class RaisingSQSClient(FakeSQSClient):
    """Raises on the first receive, then serves batches."""

    def __init__(self, batches: list[list[dict]]) -> None:
        super().__init__(batches)
        self._raised = False

    def receive_message(self, **kwargs) -> dict:
        if not self._raised:
            self._raised = True
            raise RuntimeError("simulated receive failure")
        return super().receive_message(**kwargs)


@pytest.fixture
def dispatched(monkeypatch):
    """Record every envelope handed to simulate_call, at dispatch time."""
    calls: list[dict] = []

    async def fake_simulate(approval_event: dict, publisher) -> None:
        pass

    def recording_simulate(approval_event: dict, publisher):
        calls.append(approval_event)
        return fake_simulate(approval_event, publisher)

    monkeypatch.setattr(consumer_module, "simulate_call", recording_simulate)
    return calls


async def run_consumer(client: FakeSQSClient, publisher: object = None) -> AIOConsumer:
    consumer = AIOConsumer(queue_url="http://sqs.test/queue", publisher=publisher, sqs_client=client)
    client.on_drained = consumer.stop
    await consumer.start()
    # Let fire-and-forget simulation tasks run to completion.
    await asyncio.sleep(0)
    return consumer


class TestApprovalDispatch:
    async def test_approval_event_dispatches_the_envelope_unmodified(self, dispatched):
        envelope = approval_envelope()
        client = FakeSQSClient([[sqs_message(envelope)]])

        await run_consumer(client)

        assert dispatched == [envelope]

    async def test_processed_message_is_deleted(self, dispatched):
        client = FakeSQSClient([[sqs_message(approval_envelope(), receipt_handle="rh-42")]])

        await run_consumer(client)

        assert client.deleted == ["rh-42"]

    async def test_one_dispatch_per_approval(self, dispatched):
        messages = [
            sqs_message(approval_envelope("evt-1"), receipt_handle="rh-1"),
            sqs_message(approval_envelope("evt-2"), receipt_handle="rh-2"),
        ]
        client = FakeSQSClient([messages])

        await run_consumer(client)

        assert [e["event_id"] for e in dispatched] == ["evt-1", "evt-2"]
        assert client.deleted == ["rh-1", "rh-2"]


class TestFiltering:
    async def test_non_approval_event_is_skipped_and_deleted(self, dispatched):
        envelope = approval_envelope()
        envelope["event_type"] = "ai.output.rejected"
        client = FakeSQSClient([[sqs_message(envelope, receipt_handle="rh-skip")]])

        await run_consumer(client)

        assert dispatched == []
        assert client.deleted == ["rh-skip"]

    async def test_malformed_body_is_deleted_without_dispatch(self, dispatched):
        client = FakeSQSClient([[{"Body": "not json", "ReceiptHandle": "rh-bad"}]])

        await run_consumer(client)

        assert dispatched == []
        assert client.deleted == ["rh-bad"]

    async def test_body_without_detail_is_deleted_without_dispatch(self, dispatched):
        client = FakeSQSClient([[{"Body": json.dumps({"source": "ocean"}), "ReceiptHandle": "rh-nd"}]])

        await run_consumer(client)

        assert dispatched == []
        assert client.deleted == ["rh-nd"]

    async def test_non_dict_detail_is_deleted_without_dispatch(self, dispatched):
        client = FakeSQSClient([[{"Body": json.dumps({"detail": "oops"}), "ReceiptHandle": "rh-str"}]])

        await run_consumer(client)

        assert dispatched == []
        assert client.deleted == ["rh-str"]


class TestFailureSemantics:
    async def test_failed_dispatch_leaves_the_message_for_redelivery(self, monkeypatch):
        def broken_simulate(approval_event: dict, publisher):
            raise RuntimeError("simulated dispatch failure")

        monkeypatch.setattr(consumer_module, "simulate_call", broken_simulate)
        client = FakeSQSClient([[sqs_message(approval_envelope(), receipt_handle="rh-fail")]])

        await run_consumer(client)

        assert client.deleted == []

    async def test_receive_failure_backs_off_and_continues(self, dispatched, monkeypatch):
        monkeypatch.setattr(consumer_module, "RECEIVE_ERROR_BACKOFF_SECONDS", 0)
        client = RaisingSQSClient([[sqs_message(approval_envelope())]])

        await run_consumer(client)

        assert len(dispatched) == 1

    async def test_delete_failure_does_not_stop_the_batch(self, dispatched):
        class DeleteFailingClient(FakeSQSClient):
            def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> None:
                raise RuntimeError("simulated delete failure")

        messages = [
            sqs_message(approval_envelope("evt-1"), receipt_handle="rh-1"),
            sqs_message(approval_envelope("evt-2"), receipt_handle="rh-2"),
        ]
        client = DeleteFailingClient([messages])

        await run_consumer(client)

        assert [e["event_id"] for e in dispatched] == ["evt-1", "evt-2"]


class TestOrderTolerance:
    async def test_reversed_delivery_dispatches_the_same_set(self, dispatched):
        """D3 evidence: each approval dispatches independently, so order cannot matter."""
        first = approval_envelope("evt-1")
        second = approval_envelope("evt-2")

        client = FakeSQSClient([[sqs_message(second, "rh-2"), sqs_message(first, "rh-1")]])
        await run_consumer(client)
        reversed_ids = {e["event_id"] for e in dispatched}

        dispatched.clear()
        client = FakeSQSClient([[sqs_message(first, "rh-1"), sqs_message(second, "rh-2")]])
        await run_consumer(client)
        in_order_ids = {e["event_id"] for e in dispatched}

        assert reversed_ids == in_order_ids == {"evt-1", "evt-2"}


class TestPolling:
    async def test_long_polls_the_configured_queue(self, dispatched):
        client = FakeSQSClient([[sqs_message(approval_envelope())]])

        await run_consumer(client)

        first_call = client.receive_calls[0]
        assert first_call["QueueUrl"] == "http://sqs.test/queue"
        assert first_call["WaitTimeSeconds"] == consumer_module.WAIT_TIME_SECONDS
        assert first_call["MaxNumberOfMessages"] == consumer_module.MAX_MESSAGES

    async def test_stop_ends_the_loop(self, dispatched):
        client = FakeSQSClient([])

        consumer = await run_consumer(client)

        assert consumer._running is False
