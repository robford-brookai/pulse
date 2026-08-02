"""Unit tests for the local (LocalStack) topology setup (task 6.5).

Covers the `local-event-stack` requirements at the layer that needs no
emulator: the topology `apply_topology` creates is derived from
`ocean_broker.catalog` — the same table behind the Terraform rule patterns and
publisher addressing — and applying it a second time leaves an existing stack
unchanged. The fakes below implement exactly the client surface
`apply_topology` uses, mirroring the idempotency semantics of the real APIs
(create_event_bus raises on a duplicate; create_queue, put_rule and
put_targets upsert).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from ocean_broker.catalog import CONSUMER_DOMAINS, terraform_inputs
from ocean_broker.local_topology import apply_topology, main, resource_name

#: `packages/ocean`, from `packages/ocean/libs/ocean-broker/tests/`.
_COMPOSE_FILE = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.yml"


class _AlreadyExists(Exception):
    pass


class _FakeExceptions:
    ResourceAlreadyExistsException = _AlreadyExists


class FakeEventsClient:
    """In-memory EventBridge: a bus registry plus per-bus rules and targets."""

    exceptions = _FakeExceptions

    def __init__(self) -> None:
        self.buses: set[str] = set()
        self.rules: dict[str, dict[str, str]] = {}
        self.targets: dict[str, list[dict[str, str]]] = {}

    def create_event_bus(self, Name: str) -> dict[str, str]:
        if Name in self.buses:
            raise _AlreadyExists(Name)
        self.buses.add(Name)
        return {"EventBusArn": f"arn:aws:events:us-east-1:000000000000:event-bus/{Name}"}

    def put_rule(self, Name: str, EventBusName: str, EventPattern: str) -> dict[str, str]:
        assert EventBusName in self.buses
        self.rules[Name] = {"EventBusName": EventBusName, "EventPattern": EventPattern}
        return {"RuleArn": f"arn:aws:events:us-east-1:000000000000:rule/{EventBusName}/{Name}"}

    def put_targets(self, Rule: str, EventBusName: str, Targets: list[dict[str, str]]) -> dict[str, Any]:
        assert Rule in self.rules
        existing = {t["Id"]: t for t in self.targets.get(Rule, [])}
        for target in Targets:
            existing[target["Id"]] = target
        self.targets[Rule] = sorted(existing.values(), key=lambda t: t["Id"])
        return {"FailedEntryCount": 0}


class FakeSqsClient:
    """In-memory SQS: queue URLs, ARNs, and attributes keyed by queue name."""

    def __init__(self) -> None:
        self.queues: dict[str, dict[str, str]] = {}

    def create_queue(self, QueueName: str) -> dict[str, str]:
        url = f"http://localstack:4566/000000000000/{QueueName}"
        self.queues.setdefault(
            QueueName,
            {"QueueUrl": url, "QueueArn": f"arn:aws:sqs:us-east-1:000000000000:{QueueName}"},
        )
        return {"QueueUrl": self.queues[QueueName]["QueueUrl"]}

    def get_queue_attributes(self, QueueUrl: str, AttributeNames: list[str]) -> dict[str, dict[str, str]]:
        queue = self._by_url(QueueUrl)
        return {"Attributes": {name: queue[name] for name in AttributeNames if name in queue}}

    def set_queue_attributes(self, QueueUrl: str, Attributes: dict[str, str]) -> None:
        self._by_url(QueueUrl).update(Attributes)

    def _by_url(self, url: str) -> dict[str, str]:
        for queue in self.queues.values():
            if queue["QueueUrl"] == url:
                return queue
        raise AssertionError(f"unknown queue URL {url!r}")


def _state(events: FakeEventsClient, sqs: FakeSqsClient) -> dict[str, Any]:
    return copy.deepcopy({
        "buses": events.buses,
        "rules": events.rules,
        "targets": events.targets,
        "queues": sqs.queues,
    })


def test_creates_bus_and_one_rule_and_queue_per_consumer() -> None:
    events, sqs = FakeEventsClient(), FakeSqsClient()

    apply_topology(events, sqs, event_bus_name="ocean")

    assert events.buses == {"ocean"}
    assert set(events.rules) == {resource_name("ocean", consumer) for consumer in CONSUMER_DOMAINS}
    assert set(sqs.queues) == set(events.rules)
    for rule_name, targets in events.targets.items():
        assert [t["Arn"] for t in targets] == [sqs.queues[rule_name]["QueueArn"]]


def test_rule_patterns_are_the_generated_terraform_patterns() -> None:
    events, sqs = FakeEventsClient(), FakeSqsClient()

    apply_topology(events, sqs, event_bus_name="ocean")

    generated = terraform_inputs()["consumer_rule_patterns"]
    assert isinstance(generated, dict)
    for consumer, pattern in generated.items():
        assert events.rules[resource_name("ocean", consumer)]["EventPattern"] == pattern


def test_returns_queue_url_per_consumer() -> None:
    events, sqs = FakeEventsClient(), FakeSqsClient()

    queue_urls = apply_topology(events, sqs, event_bus_name="ocean")

    assert set(queue_urls) == set(CONSUMER_DOMAINS)
    for consumer, url in queue_urls.items():
        assert url == sqs.queues[resource_name("ocean", consumer)]["QueueUrl"]


def test_apply_is_idempotent() -> None:
    events, sqs = FakeEventsClient(), FakeSqsClient()

    first_result = apply_topology(events, sqs, event_bus_name="ocean")
    first_state = _state(events, sqs)

    second_result = apply_topology(events, sqs, event_bus_name="ocean")

    assert second_result == first_result
    assert _state(events, sqs) == first_state


def test_queue_policy_admits_only_the_consumers_own_rule() -> None:
    events, sqs = FakeEventsClient(), FakeSqsClient()

    apply_topology(events, sqs, event_bus_name="ocean")

    for consumer in CONSUMER_DOMAINS:
        name = resource_name("ocean", consumer)
        policy = json.loads(sqs.queues[name]["Policy"])
        (statement,) = policy["Statement"]
        assert statement["Principal"] == {"Service": "events.amazonaws.com"}
        assert statement["Action"] == "sqs:SendMessage"
        assert statement["Resource"] == sqs.queues[name]["QueueArn"]
        rule_arn = statement["Condition"]["ArnEquals"]["aws:SourceArn"]
        assert rule_arn.endswith(f"/ocean/{name}")


def test_compose_runs_no_kafka_and_wires_consumers_to_their_queues() -> None:
    """Spec `local-event-stack`: no redpanda container; consumers read their own queue."""
    services = yaml.safe_load(_COMPOSE_FILE.read_text())["services"]

    assert not [name for name in services if "redpanda" in name or "kafka" in name]
    assert "localstack" in services
    assert "localstack-init" in services

    for name, service in services.items():
        env = service.get("environment") or {}
        assert "REDPANDA_BROKERS" not in env, name

    # Every catalog consumer that runs in compose reads the queue localstack-init creates for it.
    for consumer in CONSUMER_DOMAINS:
        queue_url = services[consumer]["environment"]["SQS_QUEUE_URL"]
        assert queue_url.endswith(f"/{resource_name('ocean', consumer)}"), consumer


def test_main_builds_clients_and_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    events, sqs = FakeEventsClient(), FakeSqsClient()
    built: list[str] = []

    def fake_client(service: str, **_: Any) -> Any:
        built.append(service)
        return {"events": events, "sqs": sqs}[service]

    monkeypatch.setattr("ocean_broker.local_topology.boto3.client", fake_client)
    monkeypatch.setenv("OCEAN_EVENT_BUS_NAME", "ocean-local")

    main()

    assert sorted(built) == ["events", "sqs"]
    assert events.buses == {"ocean-local"}
    assert set(sqs.queues) == {resource_name("ocean-local", consumer) for consumer in CONSUMER_DOMAINS}
