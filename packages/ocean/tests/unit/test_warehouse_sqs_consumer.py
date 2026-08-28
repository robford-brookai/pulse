"""warehouse-sync consumes from its SQS queue, not from Kafka.

Task 5.7 (DNA-763) converts the inline `AIOConsumer` to SQS receive/delete per
design D2/D6: receive → flush to Snowflake → delete, with a failed batch left
to visibility-timeout redelivery and the queue's redrive policy (task 7.2).

Ordering verdict (design D3): **order-tolerant** — the service appends raw
events to one table; no row depends on another. Duplicate safety comes from the
flush statement itself: it MERGEs on the envelope's `event_id`, so a redelivered
message cannot produce a second row (spec `warehouse-event-sync`).
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from utils import setup_service

setup_service("warehouse-sync")

import src.main as main


def _eb_message(event_id: str, domain: str, receipt: str) -> dict:
    """An EventBridge event as it lands in SQS: envelope whole inside `detail`."""
    return {
        "ReceiptHandle": receipt,
        "Body": json.dumps({
            "version": "0",
            "id": "eb-id",
            "detail-type": domain,
            "source": "ocean",
            "detail": {"event_id": event_id, "event_type": f"{domain}.thing"},
        }),
    }


class _Cursor:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.executed: list[tuple[str, list[str]]] = []
        self.closed = False

    def execute(self, sql: str, params: list[str]) -> None:
        if self.fail:
            raise RuntimeError("snowflake rejected the batch")
        self.executed.append((sql, params))

    def close(self) -> None:
        self.closed = True


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _Cursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class _FakeSQS:
    """Returns each response in turn, then raises CancelledError to end the loop."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.receive_calls: list[dict] = []
        self.deleted: list[dict] = []

    async def receive_message(self, **kwargs: object) -> dict:
        self.receive_calls.append(kwargs)
        if not self._responses:
            raise asyncio.CancelledError
        return self._responses.pop(0)

    async def delete_message_batch(self, *, QueueUrl: str, Entries: list[dict]) -> dict:
        self.deleted.append({"QueueUrl": QueueUrl, "Entries": Entries})
        return {"Successful": [{"Id": e["Id"]} for e in Entries], "Failed": []}


# --- the Kafka consumer is gone -------------------------------------------------


def test_no_kafka_symbols_remain() -> None:
    source = inspect.getsource(main)
    assert "confluent_kafka" not in source, "warehouse-sync must not import a Kafka client"
    assert "AIOConsumer" not in source
    assert "REDPANDA_BROKERS" not in source


def test_queue_url_env_var_is_the_standard_one() -> None:
    """Every converted consumer reads SQS_QUEUE_URL — no bespoke name."""
    source = inspect.getsource(main)
    assert 'os.environ["SQS_QUEUE_URL"]' in source


# --- message parsing -------------------------------------------------------------


def test_parse_message_extracts_envelope_domain_receipt() -> None:
    msg = _eb_message("ev-1", "alerts", "rh-1")

    parsed = main._parse_message(msg)

    assert parsed is not None
    data, domain, receipt = parsed
    assert json.loads(data) == {"event_id": "ev-1", "event_type": "alerts.thing"}
    assert domain == "alerts"
    assert receipt == "rh-1"


def test_parse_message_malformed_body_is_none() -> None:
    assert main._parse_message({"ReceiptHandle": "rh", "Body": "not json"}) is None


def test_parse_message_missing_detail_type_is_none() -> None:
    body = json.dumps({"detail": {"event_id": "ev-1"}})
    assert main._parse_message({"ReceiptHandle": "rh", "Body": body}) is None


# --- flush: MERGE keyed on event_id ----------------------------------------------


async def test_flush_batch_merges_on_event_id() -> None:
    """Redelivery must not duplicate: the write is a MERGE on data:event_id."""
    cursor = _Cursor()
    batch = [('{"event_id": "ev-1"}', "alerts"), ('{"event_id": "ev-2"}', "ops")]

    await main._flush_batch(_Conn(cursor), batch)

    sql, params = cursor.executed[0]
    assert "MERGE INTO STREAMLINE.OCEAN_RAW.EVENTS" in sql
    assert "event_id" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "WHEN MATCHED" not in sql, "an existing row is never updated, only skipped"
    assert params == ['{"event_id": "ev-1"}', "alerts", '{"event_id": "ev-2"}', "ops"]
    assert cursor.closed


async def test_flush_batch_empty_is_a_no_op() -> None:
    cursor = _Cursor()
    await main._flush_batch(_Conn(cursor), [])
    assert cursor.executed == []


async def test_flush_batch_raises_so_messages_are_not_deleted() -> None:
    cursor = _Cursor(fail=True)

    with pytest.raises(RuntimeError):
        await main._flush_batch(_Conn(cursor), [('{"event_id": "ev-1"}', "alerts")])

    assert cursor.closed, "the cursor is released even when the insert fails"


# --- the receive → flush → delete loop --------------------------------------------


@pytest.fixture
def sf(monkeypatch: pytest.MonkeyPatch) -> tuple[_Conn, _Cursor]:
    cursor = _Cursor()
    conn = _Conn(cursor)
    monkeypatch.setattr(main, "_connect_snowflake", lambda: conn)
    monkeypatch.setattr(main, "BATCH_TIMEOUT_S", 0.0)
    return conn, cursor


async def test_loop_flushes_then_deletes(sf: tuple[_Conn, _Cursor]) -> None:
    conn, cursor = sf
    sqs = _FakeSQS([{"Messages": [_eb_message("ev-1", "alerts", "rh-1"), _eb_message("ev-2", "ops", "rh-2")]}])

    with pytest.raises(asyncio.CancelledError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    sql, params = cursor.executed[0]
    assert params[1::2] == ["alerts", "ops"], "the originating domain is recorded per row"
    handles = [e["ReceiptHandle"] for d in sqs.deleted for e in d["Entries"]]
    assert handles == ["rh-1", "rh-2"], "delete happens only after a successful flush"
    assert conn.closed


async def test_loop_failed_flush_leaves_messages_for_redrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _Cursor(fail=True)
    conn = _Conn(cursor)
    monkeypatch.setattr(main, "_connect_snowflake", lambda: conn)
    monkeypatch.setattr(main, "BATCH_TIMEOUT_S", 0.0)
    sqs = _FakeSQS([{"Messages": [_eb_message("ev-1", "alerts", "rh-1")]}])

    with pytest.raises(RuntimeError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert sqs.deleted == [], "a failed batch is left to visibility timeout, not deleted"
    assert conn.closed


async def test_loop_malformed_message_is_left_for_redrive(sf: tuple[_Conn, _Cursor]) -> None:
    _conn, cursor = sf
    sqs = _FakeSQS([
        {"Messages": [{"ReceiptHandle": "rh-bad", "Body": "not json"}, _eb_message("ev-1", "ops", "rh-1")]}
    ])

    with pytest.raises(asyncio.CancelledError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    _sql, params = cursor.executed[0]
    assert params[1::2] == ["ops"], "the malformed message is not written"
    handles = [e["ReceiptHandle"] for d in sqs.deleted for e in d["Entries"]]
    assert handles == ["rh-1"], "the malformed message is not deleted — redrive owns it"


async def test_loop_empty_receive_flushes_nothing(sf: tuple[_Conn, _Cursor]) -> None:
    _conn, cursor = sf
    sqs = _FakeSQS([{}])

    with pytest.raises(asyncio.CancelledError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert cursor.executed == []
    assert sqs.deleted == []


# --- a dead consumer takes the process down (DNA-1259) ---------------------------


async def test_consumer_death_terminates_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """A consumer task that dies must kill the process, not just log: uvicorn keeps /health
    green over a dead loop, so on dev a Snowflake session-token expiry (390114) left a Running
    pod with a silently backing-up queue. Exiting nonzero makes the pod restart and
    re-authenticate fresh."""
    terminated: list[bool] = []
    monkeypatch.setattr(main, "_terminate_process", lambda: terminated.append(True))

    async def dying() -> None:
        raise RuntimeError("Authentication token has expired")

    task = asyncio.get_event_loop().create_task(dying())
    await asyncio.gather(task, return_exceptions=True)

    main._log_consumer_exit(task)

    assert terminated == [True]


async def test_cancelled_consumer_does_not_terminate_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shutdown cancellation is orderly, not a death — no exit."""
    terminated: list[bool] = []
    monkeypatch.setattr(main, "_terminate_process", lambda: terminated.append(True))

    async def forever() -> None:
        await asyncio.sleep(3600)

    task = asyncio.get_event_loop().create_task(forever())
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    main._log_consumer_exit(task)

    assert terminated == []


async def test_loop_batches_across_receives(sf: tuple[_Conn, _Cursor], monkeypatch: pytest.MonkeyPatch) -> None:
    """Below the size threshold and inside the timeout, messages accumulate."""
    monkeypatch.setattr(main, "BATCH_TIMEOUT_S", 3600.0)
    _conn, cursor = sf
    sqs = _FakeSQS([
        {"Messages": [_eb_message("ev-1", "alerts", "rh-1")]},
        {"Messages": [_eb_message("ev-2", "ops", "rh-2")]},
    ])

    with pytest.raises(asyncio.CancelledError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert cursor.executed == [], "neither threshold reached — nothing flushed"
    assert sqs.deleted == [], "unflushed messages are never deleted"
