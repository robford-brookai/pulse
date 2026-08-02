"""ocean-broker: the OCEAN event catalog and publisher, and the Kafka config factory."""

from ocean_broker.catalog import (
    EVENT_SOURCE,
    LIVE_DOMAINS,
    RETIRED_DOMAINS,
    TOPIC_PREFIX,
    EventBridgeAddress,
    address_for,
    addressing_table,
    domain_for_topic,
    pattern_matches,
    rule_pattern,
)
from ocean_broker.config import build_consumer_config, build_producer_config
from ocean_broker.publisher import EventBridgePublisher

__all__ = [
    "EVENT_SOURCE",
    "LIVE_DOMAINS",
    "RETIRED_DOMAINS",
    "TOPIC_PREFIX",
    "EventBridgeAddress",
    "EventBridgePublisher",
    "address_for",
    "addressing_table",
    "build_consumer_config",
    "build_producer_config",
    "domain_for_topic",
    "pattern_matches",
    "rule_pattern",
]
