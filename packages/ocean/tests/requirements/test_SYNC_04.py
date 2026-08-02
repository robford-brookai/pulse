"""SYNC-04: warehouse delivery has no bespoke transport (task 7.1, DNA-770).

The Redpanda Connect sink and its dedicated ``ocean.warehouse-dlq`` topic are
retired. The warehouse consumes from its own EventBridge rule and SQS queue
(task 6.2) like every other consumer; the SQS consumer itself is covered by
``tests/unit/test_warehouse_sqs_consumer.py``.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_CONNECT_YAML = _ROOT / "infra" / "redpanda" / "connect.yaml"
_TOPICS_SH = _ROOT / "infra" / "redpanda" / "topics.sh"
_CATALOG_TFVARS = _ROOT / "infra" / "terraform" / "generated" / "event_catalog.auto.tfvars.json"


def test_redpanda_connect_config_removed():
    assert not _CONNECT_YAML.exists(), "connect.yaml must be deleted — the warehouse has no bespoke transport"


def test_warehouse_dlq_topic_not_provisioned():
    script = _TOPICS_SH.read_text()
    assert "warehouse-dlq" not in script, "topics.sh must no longer create ocean.warehouse-dlq"


def test_warehouse_consumes_via_generated_rule_and_queue():
    catalog = json.loads(_CATALOG_TFVARS.read_text())
    patterns = catalog["consumer_rule_patterns"]
    assert "warehouse-sync" in patterns, "warehouse-sync must have a generated consumer rule (task 6.2)"
    pattern = json.loads(patterns["warehouse-sync"])
    assert pattern["source"] == ["ocean"]
    assert set(pattern["detail-type"]) == set(catalog["event_domains"]), (
        "the warehouse rule must cover every live domain, replacing the ^ocean\\..* subscription"
    )
