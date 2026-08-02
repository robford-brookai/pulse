"""warehouse-sync — pipes Redpanda events to Snowflake OCEAN_RAW.EVENTS."""

from __future__ import annotations

import asyncio
import os
import time

import snowflake.connector
import structlog
import uvicorn
from confluent_kafka import KafkaError, Producer
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


def _make_producer(brokers: str) -> Producer:
    return Producer({"bootstrap.servers": brokers})


def _publish_to_dlq(producer: Producer, messages: list[tuple[bytes, str]]) -> None:
    for value, topic in messages:
        producer.produce(
            "ocean.warehouse-dlq",
            value=value,
            headers=[("original_topic", topic.encode())],
        )
    producer.flush()


async def _flush_batch(
    sf_conn: snowflake.connector.SnowflakeConnection,
    producer: Producer,
    batch: list[tuple[bytes, str]],
) -> None:
    if not batch:
        return
    try:
        cur = sf_conn.cursor()
        placeholders = ", ".join(["(%s, %s)"] * len(batch))
        sql = (
            f"INSERT INTO STREAMLINE.OCEAN_RAW.EVENTS (data, _topic) "
            f"SELECT PARSE_JSON(column1), column2 FROM VALUES {placeholders}"
        )
        params = []
        for v, t in batch:
            params.extend([v.decode(), t])
        cur.execute(sql, params)
        cur.close()
        log.info("batch_inserted", count=len(batch))
    except Exception:
        log.exception("batch_insert_failed", count=len(batch))
        _publish_to_dlq(producer, batch)


async def _consume_loop(brokers: str) -> None:
    sf_conn = _connect_snowflake()
    producer = _make_producer(brokers)

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
                elif msg.topic() != "ocean.warehouse-dlq":
                    batch.append((msg.value(), msg.topic()))

            elapsed = time.monotonic() - last_flush
            if len(batch) >= BATCH_SIZE or (batch and elapsed >= BATCH_TIMEOUT_S):
                await _flush_batch(sf_conn, producer, batch)
                await consumer.commit()
                batch.clear()
                last_flush = time.monotonic()
    finally:
        if batch:
            await _flush_batch(sf_conn, producer, batch)
            await consumer.commit()
        await consumer.close()
        sf_conn.close()
        log.info("consumer_closed")


@app.on_event("startup")
async def startup() -> None:
    brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    log.info("starting_consumer", brokers=brokers)
    asyncio.create_task(_consume_loop(brokers))


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8008)
