"""Kafka consumer for outreach approval events on ocean.ai-ops."""
from __future__ import annotations

import asyncio
import json
import logging

from confluent_kafka import Consumer, KafkaError

from src.call_sim import simulate_call

log = logging.getLogger(__name__)

TOPIC = "ocean.ai-ops"
GROUP_ID = "call-simulator"
FILTER_EVENT_TYPE = "ai.output.approved"


class AIOConsumer:
    """Async wrapper around confluent_kafka Consumer.

    Polls ocean.ai-ops for outreach approval events and dispatches
    call simulations as non-blocking background tasks.
    """

    def __init__(self, bootstrap_servers: str, publisher) -> None:
        self._consumer = Consumer({
            "bootstrap.servers": bootstrap_servers,
            "group.id": GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })
        self._publisher = publisher
        self._running = False

    async def start(self) -> None:
        """Subscribe and begin polling in a loop."""
        self._consumer.subscribe([TOPIC])
        self._running = True
        log.info("consumer_started", topic=TOPIC, group_id=GROUP_ID)

        loop = asyncio.get_event_loop()
        while self._running:
            msg = await loop.run_in_executor(None, self._consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("consumer_error", error=str(msg.error()))
                continue

            try:
                event_data = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                log.warning("consumer_decode_error", error=str(exc))
                self._consumer.commit(message=msg, asynchronous=False)
                continue

            if event_data.get("event_type") != FILTER_EVENT_TYPE:
                self._consumer.commit(message=msg, asynchronous=False)
                continue

            log.info(
                "approval_received",
                event_id=event_data.get("event_id"),
                correlation_id=event_data.get("correlation_id"),
            )

            # Dispatch call simulation as non-blocking task
            asyncio.create_task(simulate_call(event_data, self._publisher))

            # Commit offset after dispatching (at-least-once)
            self._consumer.commit(message=msg, asynchronous=False)

    def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False
        self._consumer.close()
        log.info("consumer_stopped")
