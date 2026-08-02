"""ocean-broker: broker config factory and the OCEAN event catalog."""

from ocean_broker.catalog import (
    EVENT_SOURCE,
    LIVE_DOMAINS,
    RETIRED_DOMAINS,
    EventBridgeAddress,
    address_for,
    addressing_table,
    pattern_matches,
    rule_pattern,
)
from ocean_broker.config import build_consumer_config, build_producer_config

__all__ = [
    "EVENT_SOURCE",
    "LIVE_DOMAINS",
    "RETIRED_DOMAINS",
    "EventBridgeAddress",
    "address_for",
    "addressing_table",
    "build_consumer_config",
    "build_producer_config",
    "pattern_matches",
    "rule_pattern",
]
