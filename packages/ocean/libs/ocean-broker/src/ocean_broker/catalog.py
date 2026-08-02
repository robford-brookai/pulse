"""Topic → ``(source, detail-type)`` catalog for the OCEAN event bus.

This module is the single source table behind design D1. Every former
``ocean.<domain>`` Kafka topic addresses as ``source = "ocean"`` and
``detail-type = "<domain>"``, and both consumers of that fact derive from
:data:`LIVE_DOMAINS` here:

* **publisher addressing** — :func:`address_for` / :func:`addressing_table`,
  which ``EventBridgePublisher`` resolves against
* **Terraform rule patterns** — :func:`rule_pattern`, serialised into
  ``infra/terraform/generated/event_catalog.auto.tfvars.json`` by
  ``scripts/generate_event_catalog.py``

Because there is one table, a rule cannot match a ``detail-type`` no publisher
can emit, and no publisher can emit one no rule matches. Neither surface is
hand-written; edit the table, regenerate, commit.

``ocean.warehouse-dlq`` is retired (design D6) and deliberately has no entry.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: EventBridge ``source`` for every OCEAN event. Constant by design: matching on a
#: ``source`` prefix is not expressible as an EventBridge pattern, so putting the
#: domain in ``detail-type`` is what lets a new domain arrive without editing rules.
EVENT_SOURCE = "ocean"

DomainName = Literal[
    "signals",
    "alerts",
    "tasks",
    "interactions",
    "outcomes",
    "patient-state",
    "tickets",
    "ai-ops",
    "audit",
    "ops",
    "logistics",
]

#: The eleven live domains, in design D1 order.
LIVE_DOMAINS: tuple[DomainName, ...] = (
    "signals",
    "alerts",
    "tasks",
    "interactions",
    "outcomes",
    "patient-state",
    "tickets",
    "ai-ops",
    "audit",
    "ops",
    "logistics",
)

#: Former topics that survive only as history. They address to nothing.
RETIRED_DOMAINS: tuple[str, ...] = ("warehouse-dlq",)

ConsumerName = Literal[
    "event-store",
    "agent-worker",
    "call-simulator",
    "control-plane",
    "graph-projection",
    "slack-bot",
    "warehouse-sync",
]

#: The seven consumers (design D2) and the domain set each one's rule matches,
#: transcribed from each consumer's Kafka subscription at conversion time.
#: ``warehouse-sync`` subscribed with the regex ``^ocean\..*``, so it takes every
#: live domain. Task 6.2's rules and queues fan out over this mapping; edit it,
#: regenerate, commit — the same discipline as :data:`LIVE_DOMAINS`.
CONSUMER_DOMAINS: Mapping[ConsumerName, tuple[DomainName, ...]] = {
    "event-store": (
        "signals",
        "alerts",
        "tasks",
        "interactions",
        "outcomes",
        "ai-ops",
        "audit",
        "logistics",
        "ops",
    ),
    "agent-worker": ("tasks",),
    "call-simulator": ("ai-ops",),
    "control-plane": (
        "alerts",
        "ops",
        "tickets",
        "logistics",
        "tasks",
        "interactions",
    ),
    "graph-projection": (
        "signals",
        "alerts",
        "tasks",
        "interactions",
        "outcomes",
        "tickets",
        "logistics",
        "ai-ops",
        "audit",
        "ops",
    ),
    "slack-bot": ("tasks", "ai-ops", "interactions", "ops", "tickets"),
    "warehouse-sync": LIVE_DOMAINS,
}

#: The namespace every retired Kafka topic carried: `ocean.<domain>`. Only
#: :func:`domain_for_topic` should need it.
TOPIC_PREFIX = "ocean."

#: Path of the generated Terraform input, relative to the ``packages/ocean`` root.
TFVARS_RELATIVE_PATH = Path("infra") / "terraform" / "generated" / "event_catalog.auto.tfvars.json"

_PACKAGE_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class EventBridgeAddress:
    """Where one domain's events land on the bus.

    Frozen because both surfaces read the same instances; a mutation here would
    desynchronise a publisher from the rule that is supposed to catch it.
    """

    source: str
    detail_type: str

    @property
    def kafka_topic(self) -> str:
        """The pre-migration topic name this address replaces."""
        return f"ocean.{self.detail_type}"


_ADDRESSES: Mapping[str, EventBridgeAddress] = {
    domain: EventBridgeAddress(source=EVENT_SOURCE, detail_type=domain) for domain in LIVE_DOMAINS
}


def address_for(domain: str) -> EventBridgeAddress:
    """Return the bus address for a live domain.

    Raises:
        KeyError: if the domain is retired or unknown. Silence here would let a
            publisher emit a ``detail-type`` no rule matches.
    """
    try:
        return _ADDRESSES[domain]
    except KeyError:
        raise KeyError(f"{domain!r} is not a live OCEAN domain; expected one of {sorted(LIVE_DOMAINS)}") from None


def domain_for_topic(topic: str) -> str:
    """Translate a former Kafka topic name to its catalog domain.

    Accepts either form — ``ocean.tasks`` or ``tasks`` — because legacy call sites
    use the prefixed name and the catalog keys on the bare domain. One shared copy
    (hoisted from per-service duplicates, task 4.14): every publish site that still
    names its destination by topic translates here.

    Raises:
        KeyError: if the result is not a live domain. Resolution happens before the
            bus is touched, so a retired or misspelled topic fails loudly instead of
            publishing to an address no rule matches.
    """
    domain = topic.removeprefix(TOPIC_PREFIX)
    address_for(domain)
    return domain


def addressing_table() -> dict[str, EventBridgeAddress]:
    """Return the full domain → address mapping as a fresh dict."""
    return dict(_ADDRESSES)


def rule_pattern(domains: Iterable[str]) -> dict[str, list[str]]:
    """Build the EventBridge event pattern matching exactly ``domains``.

    The pattern constrains ``source`` and ``detail-type`` and nothing else, so an
    ``event_type`` new to the state catalog is delivered by the existing rule for
    its domain with no pattern edit.

    Raises:
        ValueError: if ``domains`` is empty — a rule matching nothing is a
            silently dead consumer.
        KeyError: if any domain is retired or unknown.
    """
    wanted = sorted({address_for(domain).detail_type for domain in domains})
    if not wanted:
        raise ValueError("a rule pattern needs at least one domain")

    return {"source": [EVENT_SOURCE], "detail-type": wanted}


def consumer_rule_pattern(consumer: str) -> dict[str, list[str]]:
    """Build the EventBridge pattern for one consumer's rule (task 6.2).

    Raises:
        KeyError: if the consumer is not one of the seven in
            :data:`CONSUMER_DOMAINS` — a rule for an unknown consumer would
            deliver events to a queue nothing reads.
    """
    try:
        domains = CONSUMER_DOMAINS[consumer]  # type: ignore[index]
    except KeyError:
        raise KeyError(f"{consumer!r} is not an OCEAN consumer; expected one of {sorted(CONSUMER_DOMAINS)}") from None

    return rule_pattern(domains)


def pattern_matches(pattern: Mapping[str, list[str]], source: str, detail_type: str) -> bool:
    """Evaluate a pattern from :func:`rule_pattern` against one event's addressing.

    Implements only the exact-value-list subset of EventBridge pattern matching,
    which is the whole subset :func:`rule_pattern` emits. That keeps the
    round-trip between the two surfaces checkable with no bus and no local stack.
    """
    event = {"source": source, "detail-type": detail_type}

    return all(event.get(field) in allowed for field, allowed in pattern.items())


def tfvars_path() -> Path:
    """Absolute path of the committed Terraform input."""
    return _PACKAGE_ROOT / TFVARS_RELATIVE_PATH


def terraform_inputs() -> dict[str, object]:
    """Return the table shaped as Terraform variable values.

    ``domain_event_patterns`` holds pre-serialised JSON because that is what
    ``aws_cloudwatch_event_rule.event_pattern`` takes — the rule module passes the
    string straight through rather than reassembling it.
    """
    return {
        "event_source": EVENT_SOURCE,
        "event_domains": sorted(LIVE_DOMAINS),
        "domain_event_patterns": {
            domain: json.dumps(rule_pattern([domain]), separators=(",", ":")) for domain in sorted(LIVE_DOMAINS)
        },
        "consumer_rule_patterns": {
            consumer: json.dumps(consumer_rule_pattern(consumer), separators=(",", ":"))
            for consumer in sorted(CONSUMER_DOMAINS)
        },
    }


def render_tfvars_json() -> str:
    """Render :func:`terraform_inputs` exactly as the committed file must read."""
    return json.dumps(terraform_inputs(), indent=2, sort_keys=True) + "\n"
