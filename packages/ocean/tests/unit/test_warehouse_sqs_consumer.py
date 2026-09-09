"""warehouse-sync consumes from its SQS queue, not from Kafka.

Task 5.7 (DNA-763) converts the inline `AIOConsumer` to SQS receive/delete per
design D2/D6: receive → flush to Snowflake → delete, with a failed batch left
to visibility-timeout redelivery and the queue's redrive policy (task 7.2).

Ordering verdict (design D3): **order-tolerant** — the service appends raw
events to one table; no row depends on another. Duplicate safety comes from the
flush statement itself: it MERGEs on the envelope's `event_id`, so a redelivered
message cannot produce a second row (spec `warehouse-event-sync`).

Liveness (DNA-1259, DNA-1305) is the second half: the loop survives an expired
Snowflake session token by reconnecting once, and `/health` reports the consume
loop's heartbeat so a wedged pod fails its liveness probe instead of sitting
`1/1 Running` behind a backing-up queue.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import pathlib

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi import Response
from fastapi.testclient import TestClient
from snowflake.connector import errors as snowflake_errors
from utils import setup_service

setup_service("warehouse-sync")

import src.main as main

_SERVICE_DIR = pathlib.Path(main.__file__).parents[1]


@pytest.fixture(autouse=True)
def _reset_liveness_state():
    """`_heartbeat` and `_consumer_task` are module globals `/health` reads; one test's
    leftovers must not decide another's verdict."""
    main._heartbeat.reset()
    main._consumer_task = None
    yield
    main._heartbeat.reset()
    main._consumer_task = None


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
    def __init__(self, fail: bool = False, expire_first: int = 0) -> None:
        self.fail = fail
        # Number of leading executes that raise the connector's 390114 — a session token that
        # lapsed on an otherwise-open connection, which is what killed the dev consumer.
        self.expire_first = expire_first
        self.executed: list[tuple[str, list[str]]] = []
        self.closed = False

    def execute(self, sql: str, params: list[str]) -> None:
        if self.expire_first > 0:
            self.expire_first -= 1
            raise snowflake_errors.DatabaseError(
                msg="Authentication token has expired. The user must authenticate again.",
                errno=main.TOKEN_EXPIRED_ERRNO,
            )
        if self.fail:
            raise RuntimeError("snowflake rejected the batch")
        self.executed.append((sql, params))

    def close(self) -> None:
        self.closed = True


class _Conn:
    def __init__(self, cursor: _Cursor, close_raises: bool = False) -> None:
        self._cursor = cursor
        self.closed = False
        self.close_attempts = 0
        self.close_raises = close_raises

    def cursor(self) -> _Cursor:
        return self._cursor

    def close(self) -> None:
        self.close_attempts += 1
        if self.close_raises:
            raise RuntimeError("snowflake close failed on an expired session")
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
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):  # a scripted receive failure
            raise nxt
        return nxt

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


# --- an expired session token is survivable, not fatal (DNA-1305) -----------------


async def test_expired_token_reconnects_once_and_lands_the_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """390114 on an open connection is a lapsed session, not a broken warehouse. The loop
    reconnects and retries the same batch, so the messages land and are then acknowledged."""
    expired = _Conn(_Cursor(expire_first=1))
    fresh = _Conn(_Cursor())
    handed_out = [expired, fresh]
    monkeypatch.setattr(main, "_connect_snowflake", lambda: handed_out.pop(0))
    monkeypatch.setattr(main, "BATCH_TIMEOUT_S", 0.0)
    sqs = _FakeSQS([{"Messages": [_eb_message("ev-1", "alerts", "rh-1")]}])

    with pytest.raises(asyncio.CancelledError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert handed_out == [], "exactly one reconnect — not a redial per flush"
    assert expired._cursor.executed == [], "nothing committed on the expired session"
    assert len(fresh._cursor.executed) == 1, "the retry ran on the new connection"
    handles = [e["ReceiptHandle"] for d in sqs.deleted for e in d["Entries"]]
    assert handles == ["rh-1"], "the batch landed, so its receipt retires"
    assert expired.close_attempts == 1, "the expired connection is closed, not leaked"


async def test_second_consecutive_token_expiry_exits_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """A freshly minted session that is already expired is not a token problem. The retry is
    not retried: the error leaves the loop and _log_consumer_exit takes the process down, which
    is what makes the platform restart the pod."""
    conns = [_Conn(_Cursor(expire_first=1)), _Conn(_Cursor(expire_first=1))]
    handed_out = list(conns)
    monkeypatch.setattr(main, "_connect_snowflake", lambda: handed_out.pop(0))
    monkeypatch.setattr(main, "BATCH_TIMEOUT_S", 0.0)
    terminated: list[bool] = []
    monkeypatch.setattr(main, "_terminate_process", lambda: terminated.append(True))
    sqs = _FakeSQS([{"Messages": [_eb_message("ev-1", "alerts", "rh-1")]}])

    task = asyncio.get_running_loop().create_task(main._consume_loop("https://sqs/queue", sqs_client=sqs))
    with pytest.raises(snowflake_errors.DatabaseError) as caught:
        await task
    main._log_consumer_exit(task)

    assert caught.value.errno == main.TOKEN_EXPIRED_ERRNO
    assert handed_out == [], "one reconnect, then the error propagates"
    assert terminated == [True], "a consumer that cannot re-authenticate exits nonzero"
    assert sqs.deleted == [], "an unflushed batch is never acknowledged"


async def test_close_failure_does_not_mask_the_flush_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `finally` closes inside its own try/except. Otherwise a close() that throws on an
    expired session replaces the real cause, and consumer_exited names the wrong error."""
    conn = _Conn(_Cursor(fail=True), close_raises=True)
    monkeypatch.setattr(main, "_connect_snowflake", lambda: conn)
    monkeypatch.setattr(main, "BATCH_TIMEOUT_S", 0.0)
    sqs = _FakeSQS([{"Messages": [_eb_message("ev-1", "alerts", "rh-1")]}])

    with pytest.raises(RuntimeError, match="snowflake rejected the batch"):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert conn.close_attempts == 1, "close was attempted, and its own failure absorbed"


# --- the receive arm catches transport faults, not bugs ---------------------------


async def test_transient_receive_error_is_retried(sf: tuple[_Conn, _Cursor], monkeypatch: pytest.MonkeyPatch) -> None:
    _conn, cursor = sf
    monkeypatch.setattr(main, "SQS_WAIT_TIME_S", 0)
    sqs = _FakeSQS([
        EndpointConnectionError(endpoint_url="https://sqs/queue"),
        {"Messages": [_eb_message("ev-1", "alerts", "rh-1")]},
    ])

    with pytest.raises(asyncio.CancelledError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert len(cursor.executed) == 1, "a botocore transport fault is retried, not fatal"


async def test_non_botocore_receive_error_propagates(sf: tuple[_Conn, _Cursor]) -> None:
    """The bare `except Exception` this replaced logged sqs_receive_failed and looped forever:
    a pod Running, logging, consuming nothing. A bug in this process must leave the loop."""
    conn, _cursor = sf
    sqs = _FakeSQS([TypeError("receive_message() got an unexpected keyword argument")])

    with pytest.raises(TypeError):
        await main._consume_loop("https://sqs/queue", sqs_client=sqs)

    assert conn.closed, "the connection is still released on the way out"


# --- /health means something (DNA-1305) ------------------------------------------


def test_health_is_200_while_the_heartbeat_is_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    main._heartbeat.beat()
    now[0] += 1.0

    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_is_503_with_a_reason_when_the_heartbeat_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the probe: a loop that stopped turning must stop passing."""
    now = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    main._heartbeat.beat()
    now[0] += main.HEALTH_STALE_AFTER_S + 1.0

    response = TestClient(main.app).get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["reason"] == "heartbeat_stale"
    assert body["heartbeat_age_s"] > main.HEALTH_STALE_AFTER_S


async def test_health_is_503_when_the_consumer_task_has_finished() -> None:
    main._heartbeat.beat()

    async def stopped() -> None:
        return None

    task = asyncio.get_running_loop().create_task(stopped())
    await task
    main._consumer_task = task

    response = Response()
    body = await main.health(response)

    assert response.status_code == 503
    assert body["reason"] == "consumer_stopped"


# --- the probe and the threshold have to agree ------------------------------------


def _service_json() -> dict:
    path = _SERVICE_DIR / "infra" / "duplo" / "warehouse-sync.service.json"
    return json.loads(path.read_text())


def test_duplo_service_declares_both_probes_on_the_health_port() -> None:
    """No probe is how a wedged pod stayed `1/1 Running` for four days (DNA-1259)."""
    config = _service_json()["OtherDockerConfig"]

    for name in ("livenessProbe", "readinessProbe"):
        probe = config[name]
        assert probe["httpGet"]["path"] == "/health", f"{name} must probe the endpoint that knows"
        assert probe["httpGet"]["port"] == 8008, f"{name} must use the port uvicorn serves on"


def test_health_goes_stale_well_inside_the_liveness_failure_window() -> None:
    """A threshold larger than the probe's own tolerance would just move the blind spot: the
    endpoint has to turn 503 with room for the probe to fail repeatedly and restart the pod."""
    liveness = _service_json()["OtherDockerConfig"]["livenessProbe"]
    window = liveness["periodSeconds"] * liveness["failureThreshold"]

    assert window > main.HEALTH_STALE_AFTER_S, (
        f"HEALTH_STALE_AFTER_S={main.HEALTH_STALE_AFTER_S} is not under the {window}s liveness failure window"
    )
    assert main.HEALTH_STALE_AFTER_S > main.SQS_WAIT_TIME_S * 2, (
        "the threshold must clear a normal long-poll cycle, or a healthy idle loop reads as wedged"
    )
