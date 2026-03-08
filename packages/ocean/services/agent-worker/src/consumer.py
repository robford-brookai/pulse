"""Async Kafka consumer for agent-worker.

Reads from ocean.tasks, filters for task.created from control-plane only,
and dispatches to claim competition.
"""
from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer

from src.claim import compete_for_claim
from src.personas import Persona
from src.publisher import RedpandaPublisher

log = structlog.get_logger()

TOPICS = ["ocean.tasks"]

CONSUMER_CONFIG: dict = {
    "group.id": "agent-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
}


async def handle_message(
    event_data: dict,
    personas: list[Persona],
    publisher: RedpandaPublisher,
    claimed_tasks: set[str],
) -> str:
    """Process a single deserialized event. Returns status string for testing."""
    source = event_data.get("source_system", "")
    if source != "control-plane":
        log.debug("skipped_source_system", source_system=source)
        return "skipped_source"

    event_type = event_data.get("event_type", "")
    if event_type != "task.created":
        log.debug("skipped_event_type", event_type=event_type)
        return "skipped_type"

    await compete_for_claim(event_data, personas, publisher, claimed_tasks)
    return "dispatched"


async def run_consumer(
    personas: list[Persona],
    bootstrap_servers: str,
    publisher: RedpandaPublisher,
    claimed_tasks: set[str],
) -> None:
    """Run the agent-worker consumer loop."""
    conf = {**CONSUMER_CONFIG, "bootstrap.servers": bootstrap_servers}
    consumer = Consumer(conf)
    await consumer.subscribe(TOPICS)
    log.info("agent_worker_consumer_started", topics=TOPICS, brokers=bootstrap_servers)

    try:
        while True:
            msg = await consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("consumer_error", error=str(msg.error()))
                continue

            try:
                event_data = json.loads(msg.value())
                await handle_message(event_data, personas, publisher, claimed_tasks)
                await consumer.commit(message=msg)
            except Exception:
                log.exception(
                    "agent_worker_dispatch_failed",
                    offset=msg.offset(),
                    topic=msg.topic(),
                )
    finally:
        await consumer.close()
        log.info("agent_worker_consumer_closed")
