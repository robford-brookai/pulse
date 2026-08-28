"""Integration smoke: a committed ledger event reaches a bus consumer's LocalStack queue (4.5).

`ledger-relay` in `packages/ocean/infra/docker-compose.yml` runs `relay_once` (task 4.4) against
the same LocalStack stack ocean's own services publish to — no new topology, because `event-store`
already subscribes to every live domain (`ocean_broker.catalog.CONSUMER_DOMAINS`), `patient-state`
(`pulse_ledger.relay.LEDGER_DOMAIN`) included. This test drives the same three steps compose wires
end to end: commit a declaration for real (Postgres, `commit_declaration`), relay it with the real
`EventBridgePublisher` (`pulse_ledger.relay.default_publisher`), and receive it off the
`event-store` consumer queue with a region-less `boto3` client — the same shape as
`ocean/tests/integration/test_localstack_delivery.py`, one layer up the stack.

Prerequisites: Docker (LocalStack runs via testcontainers) and a local Postgres (via
`tests/conftest.py`'s throwaway cluster). Marked ``integration``; excluded from the default
`task test` run.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import boto3
import psycopg
import pytest
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.relay import LEDGER_DOMAIN, default_publisher, relay_once

_LOCALSTACK_IMAGE = "localstack/localstack:4.6"  # same tag ledger-postgres's neighbours run

#: `event-store` subscribes to every live domain (task 5.8), `patient-state` included — the
#: relay's published event lands there with no topology change of its own.
_CONSUMER = "event-store"

#: Matches the `x-localstack-env` defaults in `packages/ocean/infra/docker-compose.yml`.
_EVENT_BUS_NAME = "ocean"


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)  # noqa: S607
    except Exception:
        return False
    else:
        return result.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_available(), reason="Docker not available — skipping integration tests"),
]


@pytest.fixture(scope="module")
def localstack_endpoint() -> Iterator[str]:
    """A running LocalStack with events+sqs, yielding its host-mapped endpoint URL."""
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(_LOCALSTACK_IMAGE)
        .with_env("SERVICES", "events,sqs")
        .with_env("EAGER_SERVICE_LOADING", "1")
        .with_exposed_ports(4566)
    )
    with container:
        endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(4566)}"

        deadline = time.monotonic() + 120
        while True:
            try:
                with urllib.request.urlopen(f"{endpoint}/_localstack/health", timeout=5) as response:  # noqa: S310
                    health = json.loads(response.read())
                if all(health["services"][s] in {"available", "running"} for s in ("events", "sqs")):
                    break
            except Exception:
                if time.monotonic() > deadline:
                    raise
            time.sleep(1)

        yield endpoint


@pytest.fixture()
def bus_env(localstack_endpoint: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bus environment exactly as `ledger-relay`'s compose service supplies it.

    Everything AWS-flavoured is scrubbed first — including a developer's ``~/.aws`` — so the test
    proves this environment is sufficient, not merely present.
    """
    import os

    for key in [k for k in os.environ if k.startswith(("AWS_", "OCEAN_"))]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")

    monkeypatch.setenv("AWS_ENDPOINT_URL", localstack_endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("OCEAN_EVENT_BUS_NAME", _EVENT_BUS_NAME)


def _declare(subject_key: str) -> Declaration:
    return Declaration(
        subject_type="referral",
        subject_key=subject_key,
        event_type="referral.received",
        to_state="received",
        effective_at=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
        actor_type="system",
        actor_id="localstack-relay-test",
        producer="pulse-ledger-tests",
        payload={"note": "synthetic"},
    )


def test_committed_event_observable_on_localstack_queue(bus_env: None, ledger_db: psycopg.Connection) -> None:
    """Commit through `pulse_ledger`, relay it, and receive it off the `event-store` queue."""
    from ocean_broker.local_topology import main as apply_local_topology

    # 1. Topology, the way `localstack-init` runs it.
    apply_local_topology()

    # 2. Commit a real declaration — the event and its outbox row, one transaction.
    subject_key = f"referral-{uuid.uuid4()}"
    result = commit_declaration(ledger_db, _declare(subject_key))

    # 3. Relay it — the way `ledger-relay`'s loop does, one pass.
    relay_result = asyncio.run(relay_once(ledger_db, default_publisher()))
    assert relay_result.published == 1
    assert relay_result.dead_lettered == 0

    # 4. Receive, the way a consumer does: a region-less SQS client built from the environment.
    sqs: Any = boto3.client("sqs")
    queue_url = sqs.get_queue_url(QueueName=f"{_EVENT_BUS_NAME}-{_CONSUMER}")["QueueUrl"]

    deadline = time.monotonic() + 30
    bodies: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        messages = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=5).get("Messages", [])
        bodies.extend(json.loads(m["Body"]) for m in messages)
        if any(b["detail"].get("event_id") == str(result.event_id) for b in bodies):
            break
    else:
        pytest.fail(f"committed event {result.event_id} never reached the {_CONSUMER} queue: got {bodies!r}")

    (delivered,) = [b for b in bodies if b["detail"].get("event_id") == str(result.event_id)]
    assert delivered["source"] == "ocean"
    assert delivered["detail-type"] == LEDGER_DOMAIN
    assert delivered["detail"]["subject_type"] == "referral"
    assert delivered["detail"]["subject_key"] == subject_key
    assert delivered["detail"]["payload"] == {"note": "synthetic"}
