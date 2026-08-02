"""The one publisher every OCEAN publish site uses.

Replaces the per-service ``publish()`` implementations that grew up around
``build_producer_config``. Verification item V5 recorded the problem: there was no shared emit
library, so thirteen publish sites each carried their own copy, and six of them had a
dead-letter fallback while the other six silently dropped events the broker rejected.

Addressing is not a parameter. ``source`` and ``detail-type`` are resolved from
:mod:`ocean_broker.catalog`, the same table the Terraform rule patterns are generated from, so a
publisher cannot emit a ``detail-type`` no rule matches (design D1).

The envelope crosses the bus whole, inside EventBridge ``detail``. No envelope field is promoted
to ``source`` or ``detail-type``; in particular ``event_type`` stays inside the envelope, because
``detail-type`` carries the *domain* and must stay stable while the state catalog keeps minting
new event types.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import sqlalchemy as sa
import structlog

from ocean_broker.catalog import address_for

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

log = structlog.get_logger()

#: EventBridge caps a single PutEvents entry at 256 KB, counting the whole entry rather than
#: just ``detail``. Checked before the call so an oversized envelope dead-letters with a clear
#: reason instead of surfacing as a generic API rejection.
MAX_ENTRY_BYTES = 256 * 1024


class EventBridgeClient(Protocol):
    """The slice of a boto3 EventBridge client this module uses.

    Narrow on purpose: it keeps the tests free of botocore stubbing, and it documents exactly
    what a replacement transport would have to provide.
    """

    def put_events(self, *, Entries: list[dict[str, Any]]) -> dict[str, Any]: ...


class PublishError(Exception):
    """EventBridge rejected the event and the dead-letter write also failed."""


class EventBridgePublisher:
    """Publishes an OCEAN envelope to EventBridge, dead-lettering to Postgres on failure.

    The Postgres fallback is kept from the connector publishers rather than dropped in favour of
    the per-queue DLQs added in task 6.3. Those catch delivery failures — events EventBridge
    accepted and could not deliver. This catches *publish* failures, where the bus never
    acknowledged the event at all, and no bus-side mechanism can see those.

    Every publish site gets the fallback, including the six that previously had none. That is a
    behaviour change and a deliberate one.
    """

    def __init__(
        self,
        client: EventBridgeClient,
        event_bus_name: str,
        db_session_maker: async_sessionmaker | None = None,
    ) -> None:
        self._client = client
        self._bus = event_bus_name
        self._db_session_maker = db_session_maker

    async def publish(self, domain: str, envelope: dict[str, Any], key: str = "") -> bool:
        """Publish one envelope. Returns True if the bus accepted it.

        ``domain`` is the former topic's domain — ``alerts`` for ``ocean.alerts``. Passing an
        unknown domain raises rather than dead-lettering: that is a wiring mistake, and failing
        loudly at the call site beats discovering it in a DLQ later.

        ``key`` no longer selects a partition. It travels in the envelope because it is what the
        consumer-side sequence guards group by (design D3).
        """
        address = address_for(domain)
        if key:
            envelope = {**envelope, "key": key}

        entry = {
            "Source": address.source,
            "DetailType": address.detail_type,
            "Detail": json.dumps(envelope, separators=(",", ":")),
            "EventBusName": self._bus,
        }

        oversized = self._too_large(entry)
        if oversized:
            await self._dead_letter(key, envelope, oversized)
            return False

        try:
            response = self._client.put_events(Entries=[entry])
        except Exception as exc:
            await self._dead_letter(key, envelope, f"put_events raised: {exc}")
            return False

        # PutEvents answers 200 with per-entry failures, so a non-raising call is not success.
        if response.get("FailedEntryCount"):
            detail = (response.get("Entries") or [{}])[0]
            reason = f"{detail.get('ErrorCode', 'unknown')}: {detail.get('ErrorMessage', '')}".strip()
            await self._dead_letter(key, envelope, reason)
            return False

        log.info("event_published", domain=domain, detail_type=address.detail_type, key=key or None)
        return True

    @staticmethod
    def _too_large(entry: dict[str, Any]) -> str | None:
        size = len(json.dumps(entry, separators=(",", ":")).encode())
        if size > MAX_ENTRY_BYTES:
            return f"entry is {size} bytes, over the {MAX_ENTRY_BYTES}-byte PutEvents limit"
        return None

    async def _dead_letter(self, key: str, envelope: dict[str, Any], error: str) -> None:
        """Write a rejected event to ``failed_webhooks``.

        Raises :class:`PublishError` when there is nowhere to write. A publisher configured
        without a session maker and then asked to dead-letter has lost the event, and saying so
        is better than logging and continuing as though it had not.
        """
        payload = json.dumps(envelope, separators=(",", ":")).encode()
        if self._db_session_maker is None:
            log.error("publish_failed_no_dlq_configured", error=error)
            msg = f"publish failed with no DLQ configured, event lost: {error}"
            raise PublishError(msg)

        log.error("publish_failed_routing_to_dlq", key=key or None, error=error)
        async with self._db_session_maker() as session, session.begin():
            await session.execute(
                sa.text(
                    "INSERT INTO failed_webhooks (id, key, payload, error, created_at, retry_count) "
                    "VALUES (:id, :key, :payload, :error, :created_at, :retry_count)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "key": key,
                    "payload": payload,
                    "error": error,
                    "created_at": datetime.now(tz=UTC),
                    "retry_count": 0,
                },
            )
