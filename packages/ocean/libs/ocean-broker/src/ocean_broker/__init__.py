"""ocean-broker: Dual-mode Kafka broker config factory."""

from ocean_broker.config import build_consumer_config, build_producer_config

__all__ = ["build_consumer_config", "build_producer_config"]
