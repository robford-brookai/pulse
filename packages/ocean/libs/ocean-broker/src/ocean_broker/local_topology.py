"""Idempotent local bus/rule/queue creation for the LocalStack dev stack (task 6.5).

Replaces ``infra/redpanda/topics.sh``. The topology applied here is derived from
:mod:`ocean_broker.catalog` — the same table behind the Terraform rule patterns
and publisher addressing — so local and deployed topology cannot be maintained
separately: adding a domain or consumer to the catalog updates both with no
additional edit.

Every call is an upsert. ``create_event_bus`` is the one AWS API here that
rejects a duplicate, so its already-exists error is treated as success;
``create_queue``, ``put_rule``, ``put_targets`` and ``set_queue_attributes``
are idempotent by contract. Re-running against an existing stack therefore
succeeds and leaves it unchanged.

Run inside the compose ``localstack-init`` service as
``python -m ocean_broker.local_topology``; boto3 picks the LocalStack endpoint
up from ``AWS_ENDPOINT_URL``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
import structlog

from ocean_broker.catalog import CONSUMER_DOMAINS, consumer_rule_pattern

log = structlog.get_logger()

_DEFAULT_EVENT_BUS = "ocean"


def resource_name(event_bus_name: str, consumer: str) -> str:
    """The shared rule/queue name for one consumer — ``<bus>-<consumer>``, as Terraform names them."""
    return f"{event_bus_name}-{consumer}"


def _queue_policy(queue_arn: str, rule_arn: str) -> str:
    """The queue policy Terraform attaches: only this consumer's own rule may write to its queue."""
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowEventBridgeSendMessage",
                "Effect": "Allow",
                "Principal": {"Service": "events.amazonaws.com"},
                "Action": "sqs:SendMessage",
                "Resource": queue_arn,
                "Condition": {"ArnEquals": {"aws:SourceArn": rule_arn}},
            },
        ],
    })


def apply_topology(events_client: Any, sqs_client: Any, *, event_bus_name: str = _DEFAULT_EVENT_BUS) -> dict[str, str]:
    """Create the bus and, per consumer, its rule, queue, target and queue policy.

    Args:
        events_client: A boto3 EventBridge (``events``) client.
        sqs_client: A boto3 SQS client.
        event_bus_name: Bus to create; rule and queue names derive from it.

    Returns:
        Consumer name → queue URL, for every consumer in
        :data:`ocean_broker.catalog.CONSUMER_DOMAINS`.
    """
    try:
        events_client.create_event_bus(Name=event_bus_name)
        log.info("event_bus_created", event_bus=event_bus_name)
    except events_client.exceptions.ResourceAlreadyExistsException:
        log.info("event_bus_exists", event_bus=event_bus_name)

    queue_urls: dict[str, str] = {}
    for consumer in sorted(CONSUMER_DOMAINS):
        name = resource_name(event_bus_name, consumer)

        queue_url = sqs_client.create_queue(QueueName=name)["QueueUrl"]
        queue_arn = sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"][
            "QueueArn"
        ]

        pattern = json.dumps(consumer_rule_pattern(consumer), separators=(",", ":"))
        rule_arn = events_client.put_rule(Name=name, EventBusName=event_bus_name, EventPattern=pattern)["RuleArn"]

        events_client.put_targets(
            Rule=name,
            EventBusName=event_bus_name,
            Targets=[{"Id": f"{name}-queue", "Arn": queue_arn}],
        )
        sqs_client.set_queue_attributes(QueueUrl=queue_url, Attributes={"Policy": _queue_policy(queue_arn, rule_arn)})

        queue_urls[consumer] = queue_url
        log.info("consumer_wired", consumer=consumer, rule=name, queue_url=queue_url)

    return queue_urls


def main() -> None:
    """CLI entry point: apply the topology to the endpoint boto3 resolves from the environment."""
    event_bus_name = os.environ.get("OCEAN_EVENT_BUS_NAME", _DEFAULT_EVENT_BUS)
    events_client = boto3.client("events")
    sqs_client = boto3.client("sqs")

    queue_urls = apply_topology(events_client, sqs_client, event_bus_name=event_bus_name)
    log.info("local_topology_applied", event_bus=event_bus_name, consumers=sorted(queue_urls))


if __name__ == "__main__":  # pragma: no cover
    main()
