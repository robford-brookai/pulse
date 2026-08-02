"""EventBridge publish adapter for slack-bot outbound events.

No transport lives here: :class:`ocean_broker.EventBridgePublisher` owns the bus call, the
catalog addressing, and the ``failed_webhooks`` fallback. This module only translates the
legacy ``ocean.<domain>`` topic names the call sites still pass into the domain the shared
publisher addresses by, so every payload construction site stays untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ocean_broker import EventBridgePublisher

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_TOPIC_PREFIX = "ocean."


def domain_for_topic(topic: str) -> str:
    """Return the bus domain for a former Kafka topic name.

    A bare domain passes through unchanged, so a caller that has already been converted
    needs no special case here. Validation belongs to the catalog, not to this function:
    an unknown domain raises from ``address_for`` at publish time.
    """
    return topic.removeprefix(_TOPIC_PREFIX)


class EventPublisher:
    """Publishes slack-bot events to EventBridge, addressed by legacy topic name."""

    def __init__(
        self,
        db_session_maker: async_sessionmaker[AsyncSession] | None = None,
        region: str | None = None,
        event_bus_name: str | None = None,
    ) -> None:
        """Build the adapter over a shared publisher.

        Args:
            db_session_maker: Async session maker for the ``failed_webhooks`` fallback.
                Without one, a failed publish is logged but not durably queued.
            region: AWS region. Defaults to the shared publisher's own resolution.
            event_bus_name: Bus to publish to. Defaults to the shared publisher's.
        """
        self._publisher = EventBridgePublisher(
            region=region,
            db_session_maker=db_session_maker,
            event_bus_name=event_bus_name,
        )

    async def publish(self, topic: str, event: dict[str, Any], key: str | None = None) -> None:
        """Publish an event envelope to the domain the topic names.

        Raises:
            KeyError: If the topic names no live domain. Raised before the bus is touched.
        """
        await self._publisher.publish(domain_for_topic(topic), event, key=key)
