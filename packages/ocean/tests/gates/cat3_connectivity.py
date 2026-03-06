#!/usr/bin/env python3
"""Gate 3: External Service Connectivity
Usage: cd /path/to/ocean && python test/cat3_connectivity.py
Requires: docker compose up (or services running locally).
Tests network-level reachability — independent of auth logic.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Parse .env file if present
env_file = Path(".env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        t0 = time.time()
        fn()
        elapsed = (time.time() - t0) * 1000
        print(f"PASS: {name} ({elapsed:.0f}ms)")
    except Exception as exc:
        failures.append(f"FAIL: {name} — {exc}")


# --- PostgreSQL (pgvector/pgvector:pg16, external port 5433) ---
def test_postgres() -> None:
    import socket
    s = socket.create_connection(("localhost", 5433), timeout=5)
    s.close()

check("Postgres TCP localhost:5433", test_postgres)


# --- Redpanda / Kafka (external port 9092) ---
def test_redpanda_tcp() -> None:
    import socket
    s = socket.create_connection(("localhost", 9092), timeout=5)
    s.close()

check("Redpanda TCP localhost:9092", test_redpanda_tcp)


# --- Redpanda Pandaproxy REST API (port 8082) ---
def test_redpanda_rest() -> None:
    req = urllib.request.Request("http://localhost:8082/topics")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200, f"expected 200, got {resp.status}"

check("Redpanda REST API localhost:8082/topics", test_redpanda_rest)


# --- Hasura GraphQL Engine (external port 8090) ---
def test_hasura() -> None:
    req = urllib.request.Request("http://localhost:8090/healthz")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200, f"expected 200, got {resp.status}"

check("Hasura healthz localhost:8090", test_hasura)


# --- OCEAN service health endpoints ---
services = {
    "event-store":      8001,
    "pocar-connector":  8002,
    "graph-projection": 8003,
    "control-plane":    8004,
    "slack-bot":        8005,
    "zcc-connector":    8006,
    "stacte-bridge":    8070,
}

for svc_name, port in services.items():
    def _make_health_check(p: int):
        def fn() -> None:
            req = urllib.request.Request(f"http://localhost:{p}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200, f"expected 200, got {resp.status}"
        return fn
    check(f"{svc_name} health localhost:{port}", _make_health_check(port))


# --- Anthropic API reachability (key not required — just TCP) ---
def test_anthropic_api() -> None:
    import socket
    s = socket.create_connection(("api.anthropic.com", 443), timeout=5)
    s.close()

check("Anthropic API TCP api.anthropic.com:443", test_anthropic_api)


# --- VoyageAI API reachability ---
def test_voyageai_api() -> None:
    import socket
    s = socket.create_connection(("api.voyageai.com", 443), timeout=5)
    s.close()

check("VoyageAI API TCP api.voyageai.com:443", test_voyageai_api)


# --- Slack API reachability ---
def test_slack_api() -> None:
    import socket
    s = socket.create_connection(("slack.com", 443), timeout=5)
    s.close()

check("Slack API TCP slack.com:443", test_slack_api)


# --- Print summary ---
print()
if failures:
    for f in failures:
        print(f, file=sys.stderr)
    print(f"\nGate 3: {len(failures)} failed", file=sys.stderr)
    sys.exit(1)
else:
    print("Gate 3: all checks passed")
