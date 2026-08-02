"""SYNC-04: Redpanda Connect config handles channel errors with automatic recovery."""

from pathlib import Path

import yaml

_ROOT = Path(__file__).parents[2]
_CONNECT_YAML = _ROOT / "infra" / "redpanda" / "connect.yaml"


def _config() -> dict:
    return yaml.safe_load(_CONNECT_YAML.read_text())


def test_fallback_output_present():
    config = _config()
    assert "fallback" in config["output"], "connect.yaml output must use 'fallback' for dead-letter recovery"


def test_dlq_topic_configured():
    config = _config()
    fallback_outputs = config["output"]["fallback"]
    topics = [out.get("kafka_franz", {}).get("topic", "") for out in fallback_outputs if "kafka_franz" in out]
    assert any("ocean.warehouse-dlq" in t for t in topics), "DLQ fallback must target ocean.warehouse-dlq"


def test_consumer_group_set():
    config = _config()
    cg = config["input"]["kafka_franz"]["consumer_group"]
    assert cg == "warehouse-sync-connect", f"Expected consumer_group 'warehouse-sync-connect', got '{cg}'"


def test_path_unique_across_topics():
    """Stage path must include topic + partition to prevent cross-topic file collisions."""
    config = _config()
    snowflake_out = config["output"]["fallback"][0]["snowflake_put"]
    path = snowflake_out["path"]
    assert "@kafka_topic" in path, "path must include @kafka_topic"
    assert "@kafka_partition" in path, "path must include @kafka_partition"


def test_snowpipe_configured():
    """snowflake_put must trigger Snowpipe for auto-ingest into EVENTS table."""
    config = _config()
    snowflake_out = config["output"]["fallback"][0]["snowflake_put"]
    assert snowflake_out.get("snowpipe"), "snowpipe must be configured for auto-ingest"
