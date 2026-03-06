"""Async Kafka consumer for control-plane.

Reads from ocean.alerts (routing) and ocean.ops (connector heartbeats).
Uses a separate consumer group (control-plane-worker) so it receives events
independently of other consumers.
Manual offset commit — offset committed only AFTER successful processing.
"""
from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.handlers.alerts import handle_alert_created
from src.handlers.heartbeats import handle_connector_heartbeat

log = structlog.get_logger()

TOPICS = [
    "ocean.alerts",
    "ocean.ops",
]

CONSUMER_CONFIG: dict = {
    "group.id": "control-plane-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
}

# Handlers registered here; additional handlers added in 03-02
EVENT_HANDLERS: dict = {
    "alert.created": handle_alert_created,
    "connector.heartbeat": handle_connector_heartbeat,
}


async def dispatch(event_data: dict, session: AsyncSession) -> None:
    """Dispatch an event to the appropriate handler.

    Unknown event types are silently skipped (forward compatible).
    """
    event_type = event_data.get("event_type", "")
    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        log.debug("event_type_skipped", event_type=event_type)
        return
    await handler(event_data, session)


async def run_consumer(session_maker: async_sessionmaker, bootstrap_servers: str) -> None:
    """Run the control-plane consumer loop."""
    conf = {**CONSUMER_CONFIG, "bootstrap.servers": bootstrap_servers}
    consumer = Consumer(conf)
    await consumer.subscribe(TOPICS)
    log.info("control_plane_consumer_started", topics=TOPICS, brokers=bootstrap_servers)

    try:
        while True:
            msg = await consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error(
                    "consumer_error",
                    error=str(msg.error()),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
                continue

            try:
                event_data = json.loads(msg.value())
                async with session_maker() as session:
                    async with session.begin():
                        await dispatch(event_data, session)
                await consumer.commit(message=msg)
            except Exception:
                log.exception(
                    "control_plane_dispatch_failed_no_commit",
                    offset=msg.offset(),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
    finally:
        await consumer.close()
        log.info("control_plane_consumer_closed")
