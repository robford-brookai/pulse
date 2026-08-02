"""Redpanda producer with dead-letter queue fallback to Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog
from confluent_kafka import KafkaException
from confluent_kafka.aio import AIOProducer
from sqlalchemy.ext.asyncio import async_sessionmaker

log = structlog.get_logger()


class RedpandaPublisher:
    """Async Redpanda publisher with Postgres DLQ fallback on broker failure."""

    def __init__(self, bootstrap_servers: str, db_session_maker: async_sessionmaker | None = None) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._db_session_maker = db_session_maker
        self._producer: AIOProducer | None = None

    def _get_producer(self) -> AIOProducer:
        if self._producer is None:
            self._producer = AIOProducer({"bootstrap.servers": self._bootstrap_servers})
        return self._producer

    async def publish(self, topic: str, key: str, value: bytes) -> None:
        """Publish value to topic. On KafkaException, writes to DLQ if available and returns."""
        producer = self._get_producer()
        try:
            future = await producer.produce(topic=topic, key=key.encode(), value=value)
            await future
            log.info("event_published", topic=topic, key=key)
        except KafkaException as exc:
            log.error("publish_failed_routing_to_dlq", topic=topic, key=key, error=str(exc))
            if self._db_session_maker is not None:
                await self._write_dlq(key, value, str(exc))

    async def _write_dlq(self, key: str, value: bytes, error: str) -> None:
        """Insert failed webhook into the failed_webhooks dead-letter table."""
        async with self._db_session_maker() as session, session.begin():
            await session.execute(
                sa.text(
                    "INSERT INTO failed_webhooks (id, key, payload, error, created_at, retry_count) "
                    "VALUES (:id, :key, :payload, :error, :created_at, :retry_count)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "key": key,
                    "payload": value,
                    "error": error,
                    "created_at": datetime.now(tz=UTC),
                    "retry_count": 0,
                },
            )
        log.info("dlq_write", key=key, error=error)

    async def close(self) -> None:
        """Flush and close the producer if it was created."""
        if self._producer is not None:
            await self._producer.flush()
            await self._producer.close()
            log.info("producer_closed")
