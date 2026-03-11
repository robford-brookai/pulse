"""Async Kafka consumer for graph projection.

Reads from all Ocean topics and upserts entity state into the operational graph.
Uses a separate consumer group (graph-projection-worker) so it receives all events
independently of the event-store-consumer group.
Manual offset commit — offset committed only AFTER successful DB upsert.
"""
from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.handlers.alerts import handle_alert_claimed, handle_alert_created, handle_alert_resolved
from src.handlers.interactions import handle_call_connected, handle_call_started
from src.handlers.outcomes import handle_call_completed, handle_call_missed
from src.handlers.signals import (
    handle_signal_anomalous,
    handle_signal_missing,
    handle_signal_received,
)
from src.handlers.tasks import (
    handle_task_assigned,
    handle_task_claimed,
    handle_task_completed,
    handle_task_created,
)
from src.handlers.tickets import (
    handle_ticket_created,
    handle_ticket_resolved,
    handle_ticket_updated,
)

log = structlog.get_logger()

TOPICS = [
    "ocean.signals",
    "ocean.alerts",
    "ocean.tasks",
    "ocean.interactions",
    "ocean.outcomes",
    "ocean.tickets",
    "ocean.ai-ops",
    "ocean.audit",
]

# CRITICAL: separate consumer group from event-store-consumer
CONSUMER_CONFIG: dict = {
    "group.id": "graph-projection-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
}

EVENT_HANDLERS: dict = {
    "signal.received": handle_signal_received,
    "signal.missing": handle_signal_missing,
    "signal.anomalous": handle_signal_anomalous,
    "alert.created": handle_alert_created,
    "alert.claimed": handle_alert_claimed,
    "alert.resolved": handle_alert_resolved,
    "task.created": handle_task_created,
    "task.completed": handle_task_completed,
    "task.assigned": handle_task_assigned,
    "task.claimed": handle_task_claimed,
    "call.started": handle_call_started,
    "call.connected": handle_call_connected,
    "call.completed": handle_call_completed,
    "call.missed": handle_call_missed,
    "ticket.created": handle_ticket_created,
    "ticket.updated": handle_ticket_updated,
    "ticket.resolved": handle_ticket_resolved,
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
    """Run the graph projection consumer loop."""
    conf = {**CONSUMER_CONFIG, "bootstrap.servers": bootstrap_servers}
    consumer = Consumer(conf)
    await consumer.subscribe(TOPICS)
    log.info("graph_consumer_started", topics=TOPICS, brokers=bootstrap_servers)

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
                async with session_maker() as session, session.begin():
                    await dispatch(event_data, session)
                await consumer.commit(message=msg)
            except Exception:
                log.exception(
                    "projection_failed_no_commit",
                    offset=msg.offset(),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
    finally:
        await consumer.close()
        log.info("graph_consumer_closed")
