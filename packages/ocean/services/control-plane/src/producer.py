"""EventBridge publish site for control-plane outbound events.

The service owns no transport code: every emit goes through `EventBridgePublisher` from
`ocean-broker`, which resolves addressing from the generated event catalog and falls back to the
Postgres `failed_webhooks` table when the bus rejects a write.

What is left here is a naming adapter. Handlers and the escalation poller name their destination
by the former Kafka topic (`ocean.tasks`), and translating that to the catalog domain in one place
keeps their payload construction untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ocean_broker import EventBridgePublisher, address_for

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_TOPIC_PREFIX = "ocean."


def domain_for_topic(topic: str) -> str:
    """Translate a former Kafka topic name to its catalog domain.

    Accepts either form — `ocean.tasks` or `tasks` — because call sites use the prefixed name and
    the catalog keys on the bare domain.

    Raises:
        KeyError: if the result is not a live domain. Resolution happens before the bus is
            touched, so a retired or misspelled topic fails loudly instead of publishing to an
            address no rule matches.
    """
    domain = topic.removeprefix(_TOPIC_PREFIX)
    address_for(domain)
    return domain


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
