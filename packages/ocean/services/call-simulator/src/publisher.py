"""Redpanda publisher for call-simulator events."""

from __future__ import annotations

import asyncio
import json
import logging

from confluent_kafka import Producer

log = logging.getLogger(__name__)


class RedpandaPublisher:
    """Async wrapper around confluent_kafka Producer.

    Runs blocking produce/flush calls in a thread executor to avoid
    blocking the event loop.
    """

    def __init__(self, bootstrap_servers: str) -> None:
        self._producer = Producer({"bootstrap.servers": bootstrap_servers})

    async def publish(self, topic: str, event: dict) -> None:
        """Serialize event to JSON and produce it to the given topic."""
        payload = json.dumps(event).encode("utf-8")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._produce_sync, topic, payload)

    def _produce_sync(self, topic: str, payload: bytes) -> None:
        self._producer.produce(topic, value=payload)
        self._producer.flush()
