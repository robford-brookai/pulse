"""Integration: BrokerConfig factory → Producer → Consumer round-trip on Redpanda.

S01 demo proof — validates that the BrokerConfig factory produces working
confluent-kafka configurations by publishing a ``patient.feature.changed``
event to ``ocean.patient-state`` and consuming it back with full payload
assertion.

Prerequisites:
    - Docker must be available (Redpanda runs via testcontainers).
    - ``ocean.patient-state`` topic auto-creates on Redpanda (default config).
"""

from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest
from confluent_kafka import Consumer, Producer
from ocean_broker import build_consumer_config, build_producer_config

pytestmark = pytest.mark.integration

TOPIC = "ocean.patient-state"


@pytest.fixture()
def _broker_env(bootstrap_servers, monkeypatch):
    """Set env vars so BrokerConfig selects Redpanda mode."""
    monkeypatch.setenv("REDPANDA_BROKERS", bootstrap_servers)
    monkeypatch.delenv("MSK_BOOTSTRAP_SERVERS", raising=False)


@pytest.mark.usefixtures("_broker_env")
def test_produce_consume_roundtrip(bootstrap_servers):
    """Publish a patient.feature.changed event and consume it back.

    Proves BrokerConfig factory → confluent-kafka Producer → topic →
    confluent-kafka Consumer pipeline works end-to-end.
    """
    # -- Unique consumer group per run to avoid interference --
    group_id = f"test-roundtrip-{uuid4()}"

    # -- Build configs via factory (the thing under test) --
    producer_cfg = build_producer_config()
    consumer_cfg = build_consumer_config(group_id=group_id)

    # Sanity: factory returned the testcontainers broker address
    assert producer_cfg["bootstrap.servers"] == bootstrap_servers
    assert consumer_cfg["bootstrap.servers"] == bootstrap_servers
    assert consumer_cfg["group.id"] == group_id

    # -- Construct test payload --
    entity_id = f"test-patient-{uuid4()}"
    payload = {
        "event_type": "patient.feature.changed",
        "source_system": "mongodb-connector",
        "entity_type": "patient_feature",
        "entity_id": entity_id,
        "collection": "alerts",
        "payload": {
            "glucose_mg_dl": 250,
            "spo2_pct": 88,
            "transformed_at": "2026-03-18T21:00:00Z",
        },
    }
    message_bytes = json.dumps(payload).encode()

    # -- Produce --
    producer = Producer(producer_cfg)
    producer.produce(TOPIC, value=message_bytes, key=entity_id.encode())
    remaining = producer.flush(timeout=10)
    assert remaining == 0, f"Producer flush timed out with {remaining} messages pending"

    # -- Consume --
    consumer = Consumer(consumer_cfg)
    try:
        consumer.subscribe([TOPIC])
        consumed = None
        deadline = time.time() + 30
        while time.time() < deadline:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                continue
            consumed = msg
            break

        assert consumed is not None, "No message consumed within 30s timeout"

        # -- Assert full payload round-trip --
        received = json.loads(consumed.value())
        assert received == payload
        assert consumed.key() == entity_id.encode()
        assert consumed.topic() == TOPIC
    finally:
        consumer.close()
