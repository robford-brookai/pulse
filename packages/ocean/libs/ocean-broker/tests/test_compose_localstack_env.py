"""The compose environment must let every service build region-resolved boto3 clients (task 6.7).

botocore resolves the client region from ``AWS_DEFAULT_REGION`` — not ``AWS_REGION``, which only
our own code (``ocean_broker.config``, ``EventBridgePublisher``) reads. 8.2's equivalence run
found the compose env set only ``AWS_REGION``, so ``localstack-init`` and every SQS consumer
built region-less clients and died at startup with ``NoRegionError`` — silently, because
consumers run as fire-and-forget asyncio tasks and ``/health`` kept answering.

These tests pin the fix at both layers: the compose file provides ``AWS_DEFAULT_REGION`` to every
service on the local event stack, and that environment — exactly as compose supplies it, nothing
else — is sufficient to construct the region-less clients the services actually build.
"""

from __future__ import annotations

import re
from pathlib import Path

import boto3
import pytest
import yaml
from ocean_broker.catalog import CONSUMER_DOMAINS

_COMPOSE_FILE = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.yml"

_VAR_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>[^}]*))?\}")


def _resolve_defaults(value: str) -> str:
    """Resolve ``${VAR:-default}`` placeholders to their defaults, as compose does with no env."""
    return _VAR_PATTERN.sub(lambda m: m.group("default") or "", value)


def _compose_services() -> dict[str, dict[str, object]]:
    services: dict[str, dict[str, object]] = yaml.safe_load(_COMPOSE_FILE.read_text())["services"]
    return services


def _localstack_env() -> dict[str, str]:
    """The shared ``x-localstack-env`` anchor with compose defaults applied."""
    anchor: dict[str, str] = yaml.safe_load(_COMPOSE_FILE.read_text())["x-localstack-env"]
    return {key: _resolve_defaults(value) for key, value in anchor.items()}


def test_every_localstack_service_gets_a_botocore_region() -> None:
    """Every service on the bus — init and consumers alike — has ``AWS_DEFAULT_REGION`` set."""
    services = _compose_services()
    on_the_bus = ["localstack-init", *sorted(CONSUMER_DOMAINS)]

    for name in on_the_bus:
        env = services[name].get("environment") or {}
        assert isinstance(env, dict), name
        assert "AWS_DEFAULT_REGION" in env, f"{name} builds a region-less boto3 client without it"


def test_region_vars_stay_in_lockstep() -> None:
    """``AWS_DEFAULT_REGION`` (botocore) and ``AWS_REGION`` (ocean_broker) resolve identically.

    Both names are load-bearing — botocore reads the former, ``ocean_broker.config`` and
    ``EventBridgePublisher`` read the latter — so a drift between them would put publishers
    and consumers in different regions.
    """
    env = _localstack_env()
    assert env["AWS_DEFAULT_REGION"] == env["AWS_REGION"] != ""


def test_compose_env_alone_builds_the_clients_the_services_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke: with ONLY the compose-provided env, region-less client construction succeeds.

    ``localstack-init`` builds ``boto3.client("events")`` / ``boto3.client("sqs")`` and the SQS
    consumers build ``boto3.client("sqs")`` — none pass ``region_name``. Constructing them under
    the exact environment compose supplies is what failed with ``NoRegionError`` before 6.7.
    """
    import os

    for key in [k for k in os.environ if k.startswith("AWS_")]:
        monkeypatch.delenv(key)
    # A developer's ~/.aws/config must not rescue the test.
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")

    env = _localstack_env()
    for key, value in env.items():
        if key.startswith(("AWS_", "OCEAN_")) and key != "AWS_ENDPOINT_URL":
            monkeypatch.setenv(key, value)

    for service in ("events", "sqs"):
        client = boto3.client(service)  # exactly how local_topology.main and the consumers build it
        assert client.meta.region_name == env["AWS_DEFAULT_REGION"], service
