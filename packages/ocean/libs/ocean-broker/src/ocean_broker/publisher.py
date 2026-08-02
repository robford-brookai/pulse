"""EventBridge publisher with Postgres ``failed_webhooks`` fallback.

Addressing is never spelled out here: every ``Source``/``DetailType`` pair comes from
:mod:`ocean_broker.catalog`, the same table the Terraform rule patterns are generated from. That
is what makes it impossible for this publisher to emit a ``detail-type`` no rule matches.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ocean_broker.catalog import address_for

log = structlog.get_logger()

_DEFAULT_REGION = "us-east-1"


class EventBridgePublisher:
    """AWS EventBridge publisher with Postgres DLQ fallback on bus failure."""

    def __init__(
        self,
        region: str | None = None,
        db_session_maker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Initialize EventBridge publisher.

        Args:
            region: AWS region for EventBridge. Defaults to ``AWS_REGION``, then ``us-east-1``.
            db_session_maker: Optional async SQLAlchemy session maker for DLQ fallback. Without
                one, a failed publish is logged but not durably queued.
        """
        region = region or os.environ.get("AWS_REGION", _DEFAULT_REGION)
        self._region = region
        self._db_session_maker = db_session_maker
        self._client = boto3.client("events", region_name=region)

    async def publish(
        self, detail_type: str, event: dict[str, Any], key: str | None = None
    ) -> None:
        """Publish an event envelope to EventBridge, falling back to the Postgres DLQ.

        A bus rejection never propagates: the envelope is written to ``failed_webhooks`` and the
        failure logged, so the caller's own transaction is unaffected.

        Args:
            detail_type: The domain, which is the EventBridge detail-type (e.g. 'patient-state').
                Not the envelope's ``event_type``.
            event: The event envelope, carried whole and unmodified in ``detail``.
            key: Optional grouping key. Carried as an envelope field for consumer-side sequence
                guards; it plays no part in routing.

        Raises:
            KeyError: If detail_type is not a live domain in the event catalog. Raised before the
                bus is touched — an address no rule matches is a dead publish, not a retryable one.
        """
        address = address_for(detail_type)

        envelope = dict(event)
        if key is not None:
            envelope["key"] = key

        try:
            response = self._client.put_events(
                Entries=[
                    {
                        "Source": address.source,
                        "DetailType": address.detail_type,
                        "Detail": json.dumps(envelope),
                    }
                ]
            )
        except Exception as exc:
            await self._handle_failure(detail_type, key, envelope, str(exc))
            return

        # put_events reports per-entry rejection in the response, not by raising.
        if response.get("FailedEntryCount", 0) > 0:
            entry = response.get("Entries", [{}])[0]
            await self._handle_failure(
                detail_type, key, envelope, entry.get("ErrorMessage", "unknown error")
            )
            return

        log.info("event_published", detail_type=detail_type, key=key)

    async def _handle_failure(
        self, detail_type: str, key: str | None, envelope: dict[str, Any], error: str
    ) -> None:
        """Log a publish failure and durably queue the envelope, if a DLQ is configured."""
        log.error("eventbridge_publish_failed", detail_type=detail_type, key=key, error=error)
        session_maker = self._db_session_maker
        if session_maker is None:
            log.error("dlq_unavailable_event_dropped", detail_type=detail_type, key=key)
            return
        await self._write_dlq(session_maker, key, envelope, error)

    @staticmethod
    async def _write_dlq(
        session_maker: async_sessionmaker[AsyncSession],
        key: str | None,
        envelope: dict[str, Any],
        error: str,
    ) -> None:
        """Write a failed envelope to the Postgres ``failed_webhooks`` table.

        Args:
            session_maker: Async session maker for the connector's Postgres database.
            key: The grouping key (or None).
            envelope: The event envelope.
            error: The error message.
        """
        try:
            async with session_maker() as session, session.begin():
                await session.execute(
                    sa.text(
                        "INSERT INTO failed_webhooks "
                        "(id, key, payload, error, created_at, retry_count) "
                        "VALUES (:id, :key, :payload, :error, :created_at, :retry_count)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "key": key or "",
                        "payload": json.dumps(envelope).encode(),
                        "error": error,
                        "created_at": datetime.now(tz=UTC),
                        "retry_count": 0,
                    },
                )
            log.info("dlq_write", key=key, error=error)
        except Exception as dlq_exc:
            log.error("dlq_write_failed", key=key, error=error, dlq_error=str(dlq_exc))
