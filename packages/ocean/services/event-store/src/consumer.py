"""Async Kafka consumer for Ocean event backbone.

Reads from all Ocean topics and writes to the Postgres event store.
Uses manual offset commit (enable.auto.commit=False) — offset is committed
only AFTER the DB write succeeds. This guarantees at-least-once delivery
with idempotent writes (ON CONFLICT DO NOTHING in writer.py).
"""
from __future__ import annotations

import structlog
from confluent_kafka import KafkaError
from confluent_kafka.asyncio import Consumer

log = structlog.get_logger()

TOPICS = [
    "ocean.signals",
    "ocean.alerts",
    "ocean.tasks",
    "ocean.interactions",
    "ocean.outcomes",
    "ocean.ai-ops",
    "ocean.audit",
]


async def run_consumer(writer, bootstrap_servers: str) -> None:
    """Run the event store consumer loop.

    Args:
        writer: Module with async write_event(bytes, topic) function.
        bootstrap_servers: Kafka/Redpanda broker address(es).
    """
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": "event-store-consumer",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,  # CRITICAL: manual commit only after DB write
    }
    consumer = Consumer(conf)
    consumer.subscribe(TOPICS)
    log.info("consumer_started", topics=TOPICS, brokers=bootstrap_servers)

    try:
        while True:
            msg = await consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # Normal — reached end of partition, keep polling
                    continue
                log.error(
                    "consumer_error",
                    error=str(msg.error()),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
                continue

            try:
                await writer.write_event(msg.value(), topic=msg.topic())
                # Commit only after successful DB write — if write fails, message is redelivered
                consumer.commit(message=msg, asynchronous=False)
            except Exception:
                log.exception(
                    "write_failed_no_commit",
                    offset=msg.offset(),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
                # Do NOT commit — message will be redelivered on restart
    finally:
        consumer.close()
        log.info("consumer_closed")
