"""ocean-broker: the OCEAN event catalog and the EventBridge publisher."""

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
from ocean_broker.publisher import EventBridgePublisher, FailureMode, PublishFailed

__all__ = [
    "EVENT_SOURCE",
    "LIVE_DOMAINS",
    "RETIRED_DOMAINS",
    "TOPIC_PREFIX",
    "EventBridgeAddress",
    "EventBridgePublisher",
    "FailureMode",
    "PublishFailed",
    "address_for",
    "addressing_table",
    "domain_for_topic",
    "pattern_matches",
    "rule_pattern",
]
