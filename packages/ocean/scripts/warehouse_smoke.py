#!/usr/bin/env python3
"""Warehouse smoke test: trigger sim smoke_test, verify events appear in Snowflake within 60s.

Usage:
    uv run python scripts/warehouse_smoke.py
    uv run python scripts/warehouse_smoke.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests
import snowflake.connector


SIM_URL = os.environ.get("SIM_DRIVER_URL", "http://localhost:8060")
TIMEOUT_SECONDS = 60
POLL_INTERVAL = 5
SCENARIO = "smoke_test"


def _check_connect_container() -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "infra/docker-compose.yml",
            "ps",
            "--format",
            "json",
            "redpanda-connect",
        ],
        capture_output=True,
        text=True,
    )
    if "running" not in result.stdout.lower():
        print(
            "WARNING: redpanda-connect container not running — events will not flow to Snowflake"
        )
        sys.exit(1)


def _trigger_simulation() -> None:
    resp = requests.post(
        f"{SIM_URL}/simulate",
        json={"scenario": SCENARIO},
        timeout=10,
    )
    resp.raise_for_status()
    print(f"Simulation triggered: scenario={SCENARIO}")


def run_smoke(start_ts: datetime, timeout: int = TIMEOUT_SECONDS) -> int:
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"],
        role="OCEAN_WRITER",
        warehouse="OCEAN_WH",
        database="STREAMLINE",
        schema="OCEAN_RAW",
    )
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            elapsed = int(time.time() - (deadline - timeout))
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM EVENTS WHERE _loaded_at >= %s",
                (start_ts.strftime("%Y-%m-%d %H:%M:%S"),),
            )
            count = cur.fetchone()[0]
            cur.close()
            print(f"  [{elapsed:3d}s] OCEAN_RAW.EVENTS count since start: {count}")
            if count > 0:
                return count
            time.sleep(POLL_INTERVAL)
    finally:
        conn.close()
    raise TimeoutError(
        f"No rows appeared in OCEAN_RAW.EVENTS within {timeout}s. "
        "Check redpanda-connect logs: docker compose logs redpanda-connect"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Warehouse smoke test")
    parser.add_argument("--dry-run", action="store_true", help="Skip Snowflake query")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN: would query OCEAN_RAW.EVENTS")
        sys.exit(0)

    _check_connect_container()

    start_ts = datetime.now(timezone.utc)
    print(f"Smoke test started at {start_ts.isoformat()}")

    _trigger_simulation()
    print("Waiting 15s for scenario to complete and events to land in Redpanda...")
    time.sleep(15)

    print("Polling Snowflake OCEAN_RAW.EVENTS...")
    try:
        count = run_smoke(start_ts)
        print(f"PASS: {count} event(s) found in OCEAN_RAW.EVENTS within {TIMEOUT_SECONDS}s")
        sys.exit(0)
    except TimeoutError as e:
        print(f"FAIL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
