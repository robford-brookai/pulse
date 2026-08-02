"""warehouse-sync — pipes Redpanda events to Snowflake OCEAN_RAW.EVENTS."""

from __future__ import annotations

import asyncio
import os
import time

import snowflake.connector
import structlog
import uvicorn
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI

log = structlog.get_logger()

BATCH_SIZE = 1000
BATCH_TIMEOUT_S = 10.0
CONSUMER_GROUP = "warehouse-sync"
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


async def _flush_batch(
    sf_conn: snowflake.connector.SnowflakeConnection,
    batch: list[tuple[bytes, str]],
) -> None:
    """Insert a batch into the raw events table.

    Raises on failure. There is no local dead-letter path: the caller must leave
    the offsets uncommitted so the batch is redelivered.
    """
    if not batch:
        return
    cur = sf_conn.cursor()
    try:
        placeholders = ", ".join(["(%s, %s)"] * len(batch))
        sql = (
            f"INSERT INTO STREAMLINE.OCEAN_RAW.EVENTS (data, _topic) "
            f"SELECT PARSE_JSON(column1), column2 FROM VALUES {placeholders}"
        )
        params = []
        for v, t in batch:
            params.extend([v.decode(), t])
        cur.execute(sql, params)
    finally:
        cur.close()
    log.info("batch_inserted", count=len(batch))


async def _consume_loop(brokers: str) -> None:
    sf_conn = _connect_snowflake()

    conf = {
        "bootstrap.servers": brokers,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "topic.metadata.refresh.interval.ms": 30000,
    }
    consumer = Consumer(conf)
    await consumer.subscribe(["^ocean\\..*"])
    log.info("consumer_started", pattern="^ocean\\..*", brokers=brokers)

    batch: list[tuple[bytes, str]] = []
    last_flush = time.monotonic()

    try:
        while True:
            msg = await consumer.poll(timeout=1.0)

            if msg is not None:
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        log.error("consumer_error", error=str(msg.error()))
                    # Continue regardless (EOF is normal, other errors are logged)
                # The Redpanda Connect sink still writes this topic until task 7.1
                # removes it; skip it so its dead letters are not re-ingested.
                elif msg.topic() != "ocean.warehouse-dlq":
                    batch.append((msg.value(), msg.topic()))

            elapsed = time.monotonic() - last_flush
            if len(batch) >= BATCH_SIZE or (batch and elapsed >= BATCH_TIMEOUT_S):
                try:
                    await _flush_batch(sf_conn, batch)
                except Exception:
                    # Nothing to fall back to. Stop without committing: the batch is
                    # redelivered, and repeated failure reaches the consumer queue's
                    # redrive threshold and its DLQ (task 7.2).
                    log.exception("batch_insert_failed", count=len(batch))
                    raise
                await consumer.commit()
                batch.clear()
                last_flush = time.monotonic()
    finally:
        await consumer.close()
        sf_conn.close()
        log.info("consumer_closed")


def _log_consumer_exit(task: asyncio.Task) -> None:
    """Surface a consumer that died. Without this the exception is swallowed."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("consumer_exited", error=str(exc), exc_info=exc)


@app.on_event("startup")
async def startup() -> None:
    brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    log.info("starting_consumer", brokers=brokers)
    task = asyncio.create_task(_consume_loop(brokers))
    task.add_done_callback(_log_consumer_exit)


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8008)
