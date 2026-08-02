"""Thin Kafka publisher wrapping ocean-broker's ``build_producer_config()``.

Uses the synchronous ``produce()`` + ``poll(0)`` pattern from confluent-kafka
(NOT the async AIOProducer).  All events are JSON-serialised before sending.
"""

from __future__ import annotations

import json

import structlog
from confluent_kafka import Producer
from ocean_broker import build_producer_config

logger = structlog.get_logger(__name__)


class EventPublisher:
    """Publish JSON events to a Kafka / Redpanda topic."""

    def __init__(self) -> None:
        config = build_producer_config()
        self._producer = Producer(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(self, topic: str, key: str, payload: dict) -> None:
        """Serialise *payload* as JSON and produce to *topic*."""
        value = json.dumps(payload).encode()
        self._producer.produce(topic, value=value, key=key.encode())
        self._producer.poll(0)
        logger.info(
            "change_event_published",
            topic=topic,
            entity_id=key,
            operation_type=payload.get("operation_type"),
        )

    def flush(self, timeout: float = 5.0) -> int:
        """Flush pending messages.  Returns count of messages still in queue."""
        remaining = self._producer.flush(timeout)
        logger.info("publisher_flushed", remaining=remaining)
        return remaining

    def close(self) -> None:
        """Flush and release resources."""
        self.flush()
        logger.info("publisher_closed")
