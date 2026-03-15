#!/usr/bin/env python3
"""Warehouse smoke test: publish a test event to Redpanda, verify it appears in Snowflake.

Usage:
    uv run python scripts/warehouse_smoke.py
    uv run python scripts/warehouse_smoke.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer
from cryptography.hazmat.primitives import serialization

import snowflake.connector


TIMEOUT_SECONDS = 60
POLL_INTERVAL = 5
TEST_TOPIC = "ocean.smoke-test"


def _check_warehouse_sync() -> None:
    result = subprocess.run(
        [
            "docker", "compose", "--env-file", ".env",
            "-f", "infra/docker-compose.yml", "ps",
            "--format", "json", "warehouse-sync",
        ],
        capture_output=True,
        text=True,
    )
    if "running" not in result.stdout.lower():
        print("FAIL: warehouse-sync container not running")
        sys.exit(1)


def _publish_test_event(brokers: str) -> str:
    """Publish a single test event and return its event_id."""
    event_id = str(uuid.uuid4())
    event = {
        "event_id": event_id,
        "event_type": "smoke_test.executed",
        "source": "warehouse-smoke-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": event_id,
        "data": {"test": True},
    }
    producer = Producer({"bootstrap.servers": brokers})
    producer.produce(TEST_TOPIC, value=json.dumps(event).encode())
    producer.flush(timeout=10)
    print(f"Published test event {event_id} to {TEST_TOPIC}")
    return event_id


def _connect_snowflake() -> snowflake.connector.SnowflakeConnection:
    key_path = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    pkb = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=pkb,
        warehouse="OCEAN_WH",
        database="STREAMLINE",
        schema="OCEAN_RAW",
    )


def run_smoke(event_id: str) -> int:
    conn = _connect_snowflake()
    deadline = time.time() + TIMEOUT_SECONDS
    try:
        while time.time() < deadline:
            elapsed = int(TIMEOUT_SECONDS - (deadline - time.time()))
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM EVENTS WHERE data:event_id::STRING = %s",
                (event_id,),
            )
            count = cur.fetchone()[0]
            cur.close()
            print(f"  [{elapsed:3d}s] Matching events in OCEAN_RAW.EVENTS: {count}")
            if count > 0:
                return count
            time.sleep(POLL_INTERVAL)
    finally:
        conn.close()
    raise TimeoutError(
        f"Event {event_id} not found in OCEAN_RAW.EVENTS within {TIMEOUT_SECONDS}s. "
        "Check: docker compose -f infra/docker-compose.yml logs warehouse-sync"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Warehouse smoke test")
    parser.add_argument("--dry-run", action="store_true", help="Skip Snowflake query")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN: would query OCEAN_RAW.EVENTS")
        sys.exit(0)

    _check_warehouse_sync()

    brokers = os.environ.get("REDPANDA_BROKERS", "localhost:9092")
    print(f"Smoke test started at {datetime.now(timezone.utc).isoformat()}")

    event_id = _publish_test_event(brokers)
    print(f"Waiting for event to flow: Redpanda -> warehouse-sync -> Snowflake...")

    try:
        count = run_smoke(event_id)
        print(f"PASS: {count} event(s) found in OCEAN_RAW.EVENTS within {TIMEOUT_SECONDS}s")
        sys.exit(0)
    except TimeoutError as e:
        print(f"FAIL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
