"""graph-projection consumes from its SQS queue, not from Kafka.

Task 5.5 (DNA-761) converts `services/graph-projection/src/consumer.py` from
subscribe/poll/commit to receive/process/delete per design D2/D6: a message is
deleted only after its DB transaction commits, a failed message is left to
visibility-timeout redelivery, and repeated failure reaches the queue's redrive
policy and DLQ (task 7.2).

Ordering verdict (design D3): **MIXED → order-tolerant as converted**. Seven of
the twelve upsert sites were already guarded by a monotonic predicate; the five
that were not (`outcomes.py:44`/`:103`, `interactions.py:36`/`:72`,
`logistics.py:125`, `signals.py:59`) received event-time sequence guards in
tasks 3.1-3.4, which landed before this conversion. This task is convert only —
no guard work here.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from utils import setup_service

setup_service("graph-projection")

import src.consumer as consumer
import src.main as main


def _eb_message(event_id: str, event_type: str, receipt: str) -> dict:
    """An EventBridge event as it lands in SQS: envelope whole inside `detail`."""
    return {
        "ReceiptHandle": receipt,
        "Body": json.dumps({
            "version": "0",
            "id": "eb-id",
            "detail-type": event_type.split(".")[0],
            "source": "ocean",
            "detail": {"event_id": event_id, "event_type": event_type},
        }),
    }


class _FakeSQS:
    """Returns each response in turn, then raises CancelledError to end the loop."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.receive_calls: list[dict] = []
        self.deleted: list[str] = []
        self.calls: list[str] = []

    async def receive_message(self, **kwargs: object) -> dict:
        self.receive_calls.append(kwargs)
        if not self._responses:
            raise asyncio.CancelledError
        return self._responses.pop(0)

    async def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> dict:
        self.deleted.append(ReceiptHandle)
        self.calls.append(f"delete:{ReceiptHandle}")
        return {}


class _FakeSession:
    """Minimal async session: context manager with a begin() context manager."""

    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def begin(self) -> _FakeSession:
        return self


class _FakeSessionMaker:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session


@pytest.fixture
def session_maker() -> _FakeSessionMaker:
    return _FakeSessionMaker()


# --- the Kafka consumer is gone -------------------------------------------------


def test_no_kafka_symbols_remain_in_consumer() -> None:
    source = inspect.getsource(consumer)
    assert "confluent_kafka" not in source, "graph-projection must not import a Kafka client"
    assert "AIOConsumer" not in source
    assert "group.id" not in source
    assert "ocean.signals" not in source, "retired ocean.<domain> topic names must be gone"


def test_no_kafka_symbols_remain_in_main() -> None:
    source = inspect.getsource(main)
    assert "REDPANDA_BROKERS" not in source
    assert "bootstrap_servers" not in source


def test_queue_url_env_var_is_the_standard_one() -> None:
    """Every converted consumer reads SQS_QUEUE_URL — no bespoke name."""
    source = inspect.getsource(main)
    assert 'os.environ["SQS_QUEUE_URL"]' in source


def test_event_handlers_registry_unchanged() -> None:
    """Convert only: all 24 handler registrations survive the transport swap."""
    assert len(consumer.EVENT_HANDLERS) == 24
    for key in ("outcome.recorded", "device.associated", "signal.anomalous", "call.completed"):
        assert key in consumer.EVENT_HANDLERS


# --- message parsing -------------------------------------------------------------


def test_parse_message_extracts_envelope_and_receipt() -> None:
    msg = _eb_message("ev-1", "alert.created", "rh-1")

    parsed = consumer._parse_message(msg)

    assert parsed is not None
    event_data, receipt = parsed
    assert event_data == {"event_id": "ev-1", "event_type": "alert.created"}
    assert receipt == "rh-1"


def test_parse_message_malformed_body_is_none() -> None:
    assert consumer._parse_message({"ReceiptHandle": "rh", "Body": "not json"}) is None


def test_parse_message_missing_detail_is_none() -> None:
    body = json.dumps({"detail-type": "alerts"})
    assert consumer._parse_message({"ReceiptHandle": "rh", "Body": body}) is None


def test_parse_message_non_dict_detail_is_none() -> None:
    body = json.dumps({"detail-type": "alerts", "detail": "not a dict"})
    assert consumer._parse_message({"ReceiptHandle": "rh", "Body": body}) is None


# --- the receive → process → delete loop ------------------------------------------


async def test_loop_dispatches_then_deletes(session_maker: _FakeSessionMaker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete happens only after the DB transaction succeeds, per message."""
    order: list[str] = []

    async def fake_dispatch(event_data: dict, session: object) -> None:
        order.append(f"dispatch:{event_data['event_id']}")

    monkeypatch.setattr(consumer, "dispatch", fake_dispatch)
    sqs = _FakeSQS([
        {"Messages": [_eb_message("ev-1", "alert.created", "rh-1"), _eb_message("ev-2", "task.created", "rh-2")]}
    ])
    sqs.calls = order

    with pytest.raises(asyncio.CancelledError):
        await consumer.run_consumer(session_maker, "https://sqs/queue", sqs_client=sqs)

    assert order == ["dispatch:ev-1", "delete:rh-1", "dispatch:ev-2", "delete:rh-2"]
    assert sqs.deleted == ["rh-1", "rh-2"]


async def test_loop_failed_dispatch_leaves_message_for_redrive(
    session_maker: _FakeSessionMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A handler failure must not delete — and must not kill the loop."""

    async def failing_dispatch(event_data: dict, session: object) -> None:
        if event_data["event_id"] == "ev-bad":
            raise RuntimeError("db rejected the upsert")

    monkeypatch.setattr(consumer, "dispatch", failing_dispatch)
    sqs = _FakeSQS([
        {"Messages": [_eb_message("ev-bad", "alert.created", "rh-bad"), _eb_message("ev-2", "task.created", "rh-2")]}
    ])

    with pytest.raises(asyncio.CancelledError):
        await consumer.run_consumer(session_maker, "https://sqs/queue", sqs_client=sqs)

    assert sqs.deleted == ["rh-2"], "the failed message is left to visibility timeout"


async def test_loop_malformed_message_is_left_for_redrive(
    session_maker: _FakeSessionMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched: list[str] = []

    async def fake_dispatch(event_data: dict, session: object) -> None:
        dispatched.append(event_data["event_id"])

    monkeypatch.setattr(consumer, "dispatch", fake_dispatch)
    sqs = _FakeSQS([
        {"Messages": [{"ReceiptHandle": "rh-bad", "Body": "not json"}, _eb_message("ev-1", "alert.created", "rh-1")]}
    ])

    with pytest.raises(asyncio.CancelledError):
        await consumer.run_consumer(session_maker, "https://sqs/queue", sqs_client=sqs)

    assert dispatched == ["ev-1"], "the malformed message is never dispatched"
    assert sqs.deleted == ["rh-1"], "the malformed message is not deleted — redrive owns it"


async def test_loop_empty_receive_processes_nothing(
    session_maker: _FakeSessionMaker,
) -> None:
    sqs = _FakeSQS([{}])

    with pytest.raises(asyncio.CancelledError):
        await consumer.run_consumer(session_maker, "https://sqs/queue", sqs_client=sqs)

    assert sqs.deleted == []
    assert session_maker.sessions == []


async def test_loop_failed_delete_does_not_kill_the_loop(
    session_maker: _FakeSessionMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed delete is logged, not fatal: the redelivery is absorbed by the
    handlers' sequence guards and dedup predicates."""

    async def fake_dispatch(event_data: dict, session: object) -> None:
        return None

    monkeypatch.setattr(consumer, "dispatch", fake_dispatch)

    class _DeleteFails(_FakeSQS):
        async def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> dict:
            raise RuntimeError("sqs unavailable")

    sqs = _DeleteFails([
        {"Messages": [_eb_message("ev-1", "alert.created", "rh-1")]},
        {"Messages": [_eb_message("ev-2", "task.created", "rh-2")]},
    ])

    with pytest.raises(asyncio.CancelledError):
        await consumer.run_consumer(session_maker, "https://sqs/queue", sqs_client=sqs)

    assert len(session_maker.sessions) == 2, "processing continues past a failed delete"


async def test_loop_receive_error_retries(session_maker: _FakeSessionMaker, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consumer, "SQS_ERROR_BACKOFF_S", 0)

    class _ReceiveFlaky(_FakeSQS):
        def __init__(self, responses: list[dict]) -> None:
            super().__init__(responses)
            self.failed_once = False

        async def receive_message(self, **kwargs: object) -> dict:
            if not self.failed_once:
                self.failed_once = True
                raise RuntimeError("throttled")
            return await super().receive_message(**kwargs)

    sqs = _ReceiveFlaky([{}])

    with pytest.raises(asyncio.CancelledError):
        await consumer.run_consumer(session_maker, "https://sqs/queue", sqs_client=sqs)

    assert sqs.failed_once
    assert len(sqs.receive_calls) == 2, "the loop retried after the receive error"
