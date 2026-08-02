"""EventBridge publish site for control-plane outbound events.

The service owns no transport code: every emit goes through `EventBridgePublisher` from
`ocean-broker`, which resolves addressing from the generated event catalog and falls back to the
Postgres `failed_webhooks` table when the bus rejects a write.

Handlers and the escalation poller name their destination by the former Kafka topic
(`ocean.tasks`); the shared `domain_for_topic` from `ocean_broker.catalog` translates that to
the catalog domain (re-exported here for the tests), keeping their payload construction
untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ocean_broker import EventBridgePublisher, domain_for_topic

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["ControlPlanePublisher", "domain_for_topic"]


class ControlPlanePublisher:
    """Publishes control-plane events to EventBridge, keyed by former topic name."""

    def __init__(
        self,
        db_session_maker: async_sessionmaker[AsyncSession] | None = None,
        region: str | None = None,
        event_bus_name: str | None = None,
    ) -> None:
        """Build the publish site.

        Args:
            db_session_maker: Session maker for the `failed_webhooks` fallback. This site had no
                dead-letter path under Kafka; without a session maker a failed publish is only
                logged, so wire it wherever one is available.
            region: AWS region. Defaults to the shared publisher's resolution.
            event_bus_name: Bus to publish to. Defaults to the shared publisher's resolution.
        """
        self._publisher = EventBridgePublisher(
            region=region,
            db_session_maker=db_session_maker,
            event_bus_name=event_bus_name,
        )

    async def publish(self, topic: str, event: dict[str, Any], key: str | None = None) -> None:
        """Publish an event envelope, addressing it by the topic's domain.

        The envelope crosses the bus whole: `event_type` stays an envelope field and is never
        promoted to `detail-type`. A bus failure does not propagate to the caller.
        """
        await self._publisher.publish(domain_for_topic(topic), event, key)
