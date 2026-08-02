"""Integration smoke: a published event reaches its consumer's queue through LocalStack (task 6.7).

8.2's equivalence run was the first end-to-end execution of the committed local stack and found
every SQS consumer dying silently at startup with ``NoRegionError``: the compose env set only
``AWS_REGION`` while botocore reads ``AWS_DEFAULT_REGION``, and the consumers run as
fire-and-forget asyncio tasks, so ``/health`` kept answering while nothing consumed.

This test replays the compose flow against a real LocalStack under *exactly* the environment the
compose ``x-localstack-env`` anchor supplies — nothing more:

1. topology creation the way ``localstack-init`` runs it (``local_topology.main()``,
   clients built from the environment),
2. publish via ``EventBridgePublisher`` (region from the environment),
3. receive with a region-less ``boto3.client("sqs")``, the client every consumer builds.

If the compose env ever again stops being sufficient for region-less clients, this fails loudly
instead of regressing into the same silence.

Prerequisites: Docker (LocalStack runs via testcontainers). Marked ``integration``.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
import yaml

_COMPOSE_FILE = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.yml"

_VAR_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>[^}]*))?\}")

#: The consumer the smoke asserts delivery to. event-store subscribes to every live domain
#: (task 5.8), so any published domain must land on its queue.
_CONSUMER = "event-store"
_DOMAIN = "alerts"

_LOCALSTACK_IMAGE = "localstack/localstack:4.6"  # same tag compose runs


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_available(), reason="Docker not available — skipping integration tests"),
]


def _compose_localstack_env() -> dict[str, str]:
    """The ``x-localstack-env`` anchor with compose defaults applied — the services' whole env."""
    anchor: dict[str, str] = yaml.safe_load(_COMPOSE_FILE.read_text())["x-localstack-env"]
    return {key: _VAR_PATTERN.sub(lambda m: m.group("default") or "", value) for key, value in anchor.items()}


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
                with urllib.request.urlopen(f"{endpoint}/_localstack/health", timeout=5) as response:
                    health = json.loads(response.read())
                if all(health["services"][s] in {"available", "running"} for s in ("events", "sqs")):
                    break
            except Exception:
                if time.monotonic() > deadline:
                    raise
            time.sleep(1)

        yield endpoint


@pytest.fixture()
def compose_env(localstack_endpoint: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Environment exactly as compose supplies it, endpoint remapped to the test container.

    Everything else AWS-flavoured is scrubbed first — including a developer's ``~/.aws`` — so the
    test proves the compose env is *sufficient*, not merely present.
    """
    import os

    for key in [k for k in os.environ if k.startswith(("AWS_", "OCEAN_"))]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")

    env = _compose_localstack_env()
    env["AWS_ENDPOINT_URL"] = localstack_endpoint
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


async def test_published_event_reaches_consumer_queue(compose_env: dict[str, str]) -> None:
    """Publish through the bus and receive on the consumer queue, all with compose-env clients."""
    from ocean_broker.local_topology import main as apply_local_topology
    from ocean_broker.publisher import EventBridgePublisher

    # 1. Topology, the way the localstack-init service runs it.
    apply_local_topology()

    # 2. Publish, the way a connector does: region and bus name resolved from the environment.
    event_id = f"smoke-{uuid.uuid4()}"
    envelope = {
        "event_id": event_id,
        "event_type": "alert.raised",
        "entity_id": "synthetic-patient-1",
        "payload": {"severity": "CRITICAL", "synthetic": True},
    }
    await EventBridgePublisher().publish(_DOMAIN, envelope, key="synthetic-patient-1")

    # 3. Receive, the way a consumer does: a region-less SQS client built from the environment.
    sqs: Any = boto3.client("sqs")
    queue_url = sqs.get_queue_url(QueueName=f"{compose_env['OCEAN_EVENT_BUS_NAME']}-{_CONSUMER}")["QueueUrl"]

    deadline = time.monotonic() + 30
    bodies: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        messages = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=5).get("Messages", [])
        bodies.extend(json.loads(m["Body"]) for m in messages)
        if any(b["detail"].get("event_id") == event_id for b in bodies):
            break
    else:
        pytest.fail(f"published event {event_id} never reached the {_CONSUMER} queue: got {bodies!r}")

    (delivered,) = [b for b in bodies if b["detail"].get("event_id") == event_id]
    assert delivered["source"] == "ocean"
    assert delivered["detail-type"] == _DOMAIN
    assert delivered["detail"]["key"] == "synthetic-patient-1"
    assert delivered["detail"]["payload"] == {"severity": "CRITICAL", "synthetic": True}
