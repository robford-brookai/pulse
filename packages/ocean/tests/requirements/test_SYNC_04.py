"""SYNC-04: Redpanda Connect config handles channel errors with automatic recovery."""
from pathlib import Path

import yaml
import pytest

_ROOT = Path(__file__).parents[2]
_CONNECT_YAML = _ROOT / "infra" / "redpanda" / "connect.yaml"


def _config() -> dict:
    return yaml.safe_load(_CONNECT_YAML.read_text())


def test_fallback_output_present():
    config = _config()
    assert "fallback" in config["output"], \
        "connect.yaml output must use 'fallback' for dead-letter recovery"


def test_dlq_topic_configured():
    config = _config()
    fallback_outputs = config["output"]["fallback"]
    topics = [
        out.get("kafka_franz", {}).get("topic", "")
        for out in fallback_outputs
        if "kafka_franz" in out
    ]
    assert any("ocean.warehouse-dlq" in t for t in topics), \
        "DLQ fallback must target ocean.warehouse-dlq"


def test_consumer_group_set():
    config = _config()
    cg = config["input"]["kafka_franz"]["consumer_group"]
    assert cg == "warehouse-sync-connect", \
        f"Expected consumer_group 'warehouse-sync-connect', got '{cg}'"


def test_offset_token_unique_across_topics():
    """Offset token must include topic + partition to prevent cross-topic dedup collisions."""
    config = _config()
    snowflake_out = config["output"]["fallback"][0]["snowflake_streaming"]
    offset_token = snowflake_out["offset_token"]
    assert "@kafka_topic" in offset_token, "offset_token must include @kafka_topic"
    assert "@kafka_partition" in offset_token, "offset_token must include @kafka_partition"


def test_schema_evolution_disabled():
    """VARIANT table; no column addition wanted — schema_evolution must be false."""
    config = _config()
    snowflake_out = config["output"]["fallback"][0]["snowflake_streaming"]
    se = snowflake_out.get("schema_evolution", {})
    assert se.get("enabled") is False, "schema_evolution.enabled must be false"
