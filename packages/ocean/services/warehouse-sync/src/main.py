"""warehouse-sync — pipes OCEAN bus events from its SQS queue to Snowflake OCEAN_RAW.EVENTS."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import snowflake.connector
import structlog
import uvicorn
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI

log = structlog.get_logger()

BATCH_SIZE = 1000
BATCH_TIMEOUT_S = 10.0
SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME_S = 5
SQS_DELETE_CHUNK = 10
app = FastAPI(title="warehouse-sync", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "warehouse-sync", "version": "0.1.0"}


def _connect_snowflake() -> snowflake.connector.SnowflakeConnection:
    key_path = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    pkb = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=pkb,
        warehouse="OCEAN_WH",
        database="STREAMLINE",
        schema="OCEAN_RAW",
    )


def _parse_message(msg: dict[str, Any]) -> tuple[str, str, str] | None:
    """Extract (envelope json, domain, receipt handle) from an EventBridge→SQS message.

    The EventBridge event carries the envelope whole in ``detail`` and the domain in
    ``detail-type``. A message that does not parse is returned as None and left
    undeleted, so the queue's redrive policy moves it to the DLQ.
    """
    receipt = msg["ReceiptHandle"]
    try:
        body = json.loads(msg["Body"])
        domain = body["detail-type"]
        detail = body["detail"]
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("malformed_message", receipt_handle=receipt)
        return None
    if not isinstance(domain, str):
        log.warning("malformed_message", receipt_handle=receipt)
        return None
    return json.dumps(detail), domain, receipt


async def _flush_batch(
    sf_conn: snowflake.connector.SnowflakeConnection,
    batch: list[tuple[str, str]],
) -> None:
    """MERGE a batch into the raw events table, keyed on the envelope's event_id.

    A row whose event_id already exists is skipped, never updated — so a message
    redelivered after a lost delete cannot produce a duplicate row. Raises on
    failure: the caller must leave the messages undeleted so they are redelivered.
    """
    if not batch:
        return
    cur = sf_conn.cursor()
    try:
        placeholders = ", ".join(["(%s, %s)"] * len(batch))
        sql = (
            f"MERGE INTO STREAMLINE.OCEAN_RAW.EVENTS t USING ("
            f"SELECT PARSE_JSON(column1) AS data, column2 AS domain "
            f"FROM VALUES {placeholders} "
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY data:event_id ORDER BY column2) = 1"
            f") s ON t.data:event_id = s.data:event_id "
            f"WHEN NOT MATCHED THEN INSERT (data, _topic) VALUES (s.data, s.domain)"
        )
        params: list[str] = []
        for data, domain in batch:
            params.extend([data, domain])
        cur.execute(sql, params)
    finally:
        cur.close()
    log.info("batch_merged", count=len(batch))


async def _delete_messages(sqs_client: Any, queue_url: str, receipts: list[str]) -> None:
    """Delete processed messages. A failed delete is logged, not retried: the
    message redelivers, and the MERGE makes the redelivery a no-op."""
    for i in range(0, len(receipts), SQS_DELETE_CHUNK):
        chunk = receipts[i : i + SQS_DELETE_CHUNK]
        entries = [{"Id": str(j), "ReceiptHandle": r} for j, r in enumerate(chunk)]
        try:
            resp = await sqs_client.delete_message_batch(QueueUrl=queue_url, Entries=entries)
        except Exception:
            log.exception("sqs_delete_failed", count=len(chunk))
            continue
        failed = resp.get("Failed", [])
        if failed:
            log.warning("sqs_delete_partial_failure", count=len(failed))


async def _consume_loop(queue_url: str, *, sqs_client: Any = None) -> None:
    """Receive → flush to Snowflake → delete.

    At-least-once, delete-after-success: a failed flush raises, the messages stay
    on the queue past their visibility timeout, and repeated failure reaches the
    queue's redrive threshold and its DLQ (task 7.2).
    """
    sf_conn = _connect_snowflake()
    owns_client = sqs_client is None
    if owns_client:
        import aioboto3

        session = aioboto3.Session()
        sqs_client = await session.client("sqs").__aenter__()
    log.info("consumer_started", queue_url=queue_url)

    batch: list[tuple[str, str]] = []
    receipts: list[str] = []
    last_flush = time.monotonic()

    try:
        while True:
            try:
                response = await sqs_client.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=SQS_MAX_MESSAGES,
                    WaitTimeSeconds=SQS_WAIT_TIME_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sqs_receive_failed", queue_url=queue_url)
                await asyncio.sleep(SQS_WAIT_TIME_S)
                continue

            for msg in response.get("Messages", []):
                parsed = _parse_message(msg)
                if parsed is None:
                    continue
                data, domain, receipt = parsed
                batch.append((data, domain))
                receipts.append(receipt)

            elapsed = time.monotonic() - last_flush
            if len(batch) >= BATCH_SIZE or (batch and elapsed >= BATCH_TIMEOUT_S):
                try:
                    await _flush_batch(sf_conn, batch)
                except Exception:
                    # Nothing to fall back to. Stop without deleting: the batch is
                    # redelivered, and repeated failure reaches the queue's redrive
                    # threshold and its DLQ (task 7.2).
                    log.exception("batch_insert_failed", count=len(batch))
                    raise
                await _delete_messages(sqs_client, queue_url, receipts)
                batch.clear()
                receipts.clear()
                last_flush = time.monotonic()
    finally:
        if owns_client:
            await sqs_client.__aexit__(None, None, None)
        sf_conn.close()
        log.info("consumer_closed")


def _terminate_process() -> None:
    """Exit nonzero immediately. Module-level seam so tests can observe the call."""
    os._exit(1)


def _log_consumer_exit(task: asyncio.Task) -> None:
    """Surface a consumer that died — then take the process down with it.

    Logging alone leaves uvicorn serving /health green over a dead loop: on dev a Snowflake
    session-token expiry (390114) killed the consumer and the queue backed up silently behind a
    Running pod (DNA-1259). Exiting nonzero makes the platform restart the pod, which
    re-authenticates fresh — a Running pod is a consuming pod again. Orderly cancellation
    (shutdown) is not a death and exits nothing.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("consumer_exited", error=str(exc), exc_info=exc)
        _terminate_process()


@app.on_event("startup")
async def startup() -> None:
    queue_url = os.environ["SQS_QUEUE_URL"]
    log.info("starting_consumer", queue_url=queue_url)
    task = asyncio.create_task(_consume_loop(queue_url))
    task.add_done_callback(_log_consumer_exit)


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8008)
