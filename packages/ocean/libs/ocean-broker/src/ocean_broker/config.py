"""Dual-mode Kafka broker configuration factory.

Returns confluent-kafka config dicts for two modes:
- **Redpanda** (local dev): plaintext, no auth
- **MSK Serverless** (production): SASL_SSL + OAUTHBEARER with IAM auth

Detection: if ``MSK_BOOTSTRAP_SERVERS`` env var is set → MSK mode,
otherwise use ``REDPANDA_BROKERS`` (default ``localhost:9092``).
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

_DEFAULT_REDPANDA_BROKERS = "localhost:9092"


def _is_msk_mode() -> bool:
    return bool(os.environ.get("MSK_BOOTSTRAP_SERVERS"))


def _msk_oauth_cb(config: str) -> tuple[str, float]:
    """OAUTHBEARER token callback for MSK Serverless IAM auth.

    Lazily imports ``aws_msk_iam_sasl_signer`` so the dependency is only
    required in MSK mode.  Returns ``(token, expiry_seconds)`` — note the
    signer returns expiry in *milliseconds*, so we divide by 1000.
    """
    from aws_msk_iam_sasl_signer.MSKAuthTokenProvider import generate_auth_token

    region = os.environ.get("AWS_REGION", "us-east-1")
    token, expiry_ms = generate_auth_token(region)

    log.debug("oauth_token_generated", region=region)

    return token, expiry_ms / 1000


def _base_config() -> dict[str, Any]:
    """Build the base config dict common to both producer and consumer."""
    if _is_msk_mode():
        return {
            "bootstrap.servers": os.environ["MSK_BOOTSTRAP_SERVERS"],
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "OAUTHBEARER",
            "oauth_cb": _msk_oauth_cb,
            "connections.max.idle.ms": 540_000,
        }

    brokers = os.environ.get("REDPANDA_BROKERS", _DEFAULT_REDPANDA_BROKERS)
    return {"bootstrap.servers": brokers}


def build_producer_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a confluent-kafka producer config dict.

    Args:
        overrides: Optional dict merged last so callers can override any key.
    """
    cfg = _base_config()
    if overrides:
        cfg.update(overrides)

    mode = "msk" if _is_msk_mode() else "redpanda"
    log.info("broker_config_created", mode=mode, role="producer")
    return cfg


def build_consumer_config(
    group_id: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a confluent-kafka consumer config dict.

    Args:
        group_id: Kafka consumer group ID.
        overrides: Optional dict merged last so callers can override any key.
    """
    cfg = _base_config()
    cfg["group.id"] = group_id
    cfg["auto.offset.reset"] = "earliest"
    cfg["enable.auto.commit"] = False

    if overrides:
        cfg.update(overrides)

    mode = "msk" if _is_msk_mode() else "redpanda"
    log.info("broker_config_created", mode=mode, role="consumer", group_id=group_id)
    return cfg
