"""Unit tests for the consumer half of the catalog (task 6.2).

Covers the `event-delivery` requirement "Each consumer has a dedicated rule and
queue" at the pattern layer: one registry of the seven consumers, each with the
domain set its rule matches, generated from the same table as publisher
addressing (task 2.1). The work-order test: each rule's pattern matches exactly
its consumer's domain set — every domain in the set, no live domain outside it,
nothing retired, nothing from a foreign source.

The registry is grounded against the consumer sources themselves for as long as
those sources still declare Kafka `TOPICS`; once wave 2c removes them, the
registry here is the sole owner of each consumer's domain set.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from ocean_broker.catalog import (
    CONSUMER_DOMAINS,
    EVENT_SOURCE,
    LIVE_DOMAINS,
    RETIRED_DOMAINS,
    consumer_rule_pattern,
    pattern_matches,
    render_tfvars_json,
    tfvars_path,
)

#: The seven consumers, transcribed from design D2 rather than imported, so the
#: registry cannot silently drift away from the design it implements.
DESIGN_D2_CONSUMERS = {
    "event-store",
    "agent-worker",
    "call-simulator",
    "control-plane",
    "graph-projection",
    "slack-bot",
    "warehouse-sync",
}

#: `packages/ocean`, from `packages/ocean/libs/ocean-broker/tests/`.
_REPO_OCEAN = Path(__file__).resolve().parents[3]
_SERVICES = _REPO_OCEAN / "services"

#: Where each consumer's pre-conversion Kafka subscription lives.
_CONSUMER_SOURCES = {
    "event-store": _SERVICES / "event-store" / "src" / "consumer.py",
    "agent-worker": _SERVICES / "agent-worker" / "src" / "consumer.py",
    "call-simulator": _SERVICES / "call-simulator" / "src" / "consumer.py",
    "control-plane": _SERVICES / "control-plane" / "src" / "consumer.py",
    "graph-projection": _SERVICES / "graph-projection" / "src" / "consumer.py",
    "slack-bot": _SERVICES / "slack-bot" / "src" / "consumer.py",
    "warehouse-sync": _SERVICES / "warehouse-sync" / "src" / "main.py",
}


def _declared_topic_domains(source: Path) -> set[str] | None:
    """Extract the domains a consumer source subscribes to, or None once converted.

    Reads only the `TOPICS = [...]` / `TOPIC = "..."` declaration, not the whole
    file — a consumer that also publishes would otherwise contribute its publish
    topics. A subscribe-all regex (`warehouse-sync`) means every live domain.
    """
    text = source.read_text()

    if re.search(r'subscribe\(\["\^ocean', text):
        return set(LIVE_DOMAINS)

    block = re.search(r'^TOPICS?\s*=\s*(\[[^\]]*\]|"[^"]*")', text, re.MULTILINE)
    if block is None:
        return None

    return set(re.findall(r'"ocean\.([a-z-]+)"', block.group(1)))


class TestConsumerRegistry:
    """The registry itself: seven consumers, each with a non-empty live domain set."""

    def test_exactly_the_seven_design_consumers(self):
        assert set(CONSUMER_DOMAINS) == DESIGN_D2_CONSUMERS
        assert len(CONSUMER_DOMAINS) == 7

    @pytest.mark.parametrize("consumer", sorted(DESIGN_D2_CONSUMERS))
    def test_domain_set_is_non_empty_live_and_duplicate_free(self, consumer):
        domains = CONSUMER_DOMAINS[consumer]

        assert domains, f"{consumer} subscribes to nothing — its rule would match nothing"
        assert set(domains) <= set(LIVE_DOMAINS)
        assert len(set(domains)) == len(domains)

    def test_warehouse_sync_subscribes_to_every_live_domain(self):
        """Its Kafka subscription was `^ocean\\..*`; the queue must keep that width."""
        assert set(CONSUMER_DOMAINS["warehouse-sync"]) == set(LIVE_DOMAINS)

    def test_unknown_consumer_has_no_pattern(self):
        with pytest.raises(KeyError):
            consumer_rule_pattern("not-a-consumer")


class TestPatternsMatchExactlyTheConsumerDomainSet:
    """The work-order test, verbatim: exact match, per consumer."""

    @pytest.mark.parametrize("consumer", sorted(DESIGN_D2_CONSUMERS))
    def test_every_subscribed_domain_is_matched(self, consumer):
        pattern = consumer_rule_pattern(consumer)

        for domain in CONSUMER_DOMAINS[consumer]:
            assert pattern_matches(pattern, EVENT_SOURCE, domain)

    @pytest.mark.parametrize("consumer", sorted(DESIGN_D2_CONSUMERS))
    def test_no_unsubscribed_live_domain_is_matched(self, consumer):
        """`event-delivery`: no consumer receives events it does not subscribe to."""
        pattern = consumer_rule_pattern(consumer)

        for domain in set(LIVE_DOMAINS) - set(CONSUMER_DOMAINS[consumer]):
            assert not pattern_matches(pattern, EVENT_SOURCE, domain)

    @pytest.mark.parametrize("consumer", sorted(DESIGN_D2_CONSUMERS))
    def test_no_retired_domain_is_matched(self, consumer):
        pattern = consumer_rule_pattern(consumer)

        for domain in RETIRED_DOMAINS:
            assert not pattern_matches(pattern, EVENT_SOURCE, domain)

    @pytest.mark.parametrize("consumer", sorted(DESIGN_D2_CONSUMERS))
    def test_no_foreign_source_is_matched(self, consumer):
        pattern = consumer_rule_pattern(consumer)

        assert not pattern_matches(pattern, "not-ocean", next(iter(CONSUMER_DOMAINS[consumer])))

    def test_fan_out_domains_are_matched_by_every_subscriber(self):
        """`event-delivery`: every subscribing consumer gets its own copy."""
        for domain in LIVE_DOMAINS:
            subscribers = [c for c, domains in CONSUMER_DOMAINS.items() if domain in domains]

            for consumer in subscribers:
                assert pattern_matches(consumer_rule_pattern(consumer), EVENT_SOURCE, domain)


class TestRegistryMatchesTheConsumerSources:
    """Grounding: the registry transcribes what each consumer actually subscribes to.

    Valid only while the sources still hold their Kafka subscription (pre wave 2c);
    a converted consumer no longer declares topics, and the registry takes over.
    """

    @pytest.mark.parametrize("consumer", sorted(DESIGN_D2_CONSUMERS))
    def test_registry_equals_the_declared_subscription(self, consumer):
        declared = _declared_topic_domains(_CONSUMER_SOURCES[consumer])
        if declared is None:
            pytest.skip(f"{consumer} is converted; the catalog registry now owns its domain set")

        assert set(CONSUMER_DOMAINS[consumer]) == declared


class TestEventStoreSubscribesToEveryLiveDomain:
    """Task 5.8: the append-only store takes all eleven live domains.

    The Kafka subscription it was transcribed from omitted `tickets` and
    `patient-state` while its docstring claimed "all Ocean topics". Those two
    are asserted by name so a future narrowing fails loudly here, not only by
    set arithmetic.
    """

    def test_event_store_takes_every_live_domain(self):
        assert CONSUMER_DOMAINS["event-store"] == LIVE_DOMAINS

    @pytest.mark.parametrize("domain", ["tickets", "patient-state"])
    def test_previously_missing_domains_by_name(self, domain):
        assert domain in CONSUMER_DOMAINS["event-store"]
        assert pattern_matches(consumer_rule_pattern("event-store"), EVENT_SOURCE, domain)

    def test_committed_tfvars_pattern_covers_every_live_domain(self):
        """Round-trip: the committed artifact, not just the in-memory table."""
        committed = json.loads(tfvars_path().read_text())
        pattern = json.loads(committed["consumer_rule_patterns"]["event-store"])

        assert pattern == consumer_rule_pattern("event-store")
        assert pattern["detail-type"] == sorted(LIVE_DOMAINS)
        assert "tickets" in pattern["detail-type"]
        assert "patient-state" in pattern["detail-type"]


class TestGeneratedTerraformInput:
    """The consumer patterns reach Terraform through the same generated artifact."""

    def test_tfvars_exposes_one_pattern_per_consumer(self):
        emitted = json.loads(render_tfvars_json())

        assert set(emitted["consumer_rule_patterns"]) == DESIGN_D2_CONSUMERS

    def test_tfvars_patterns_are_json_strings_that_round_trip(self):
        emitted = json.loads(render_tfvars_json())

        for consumer, encoded in emitted["consumer_rule_patterns"].items():
            assert isinstance(encoded, str)
            assert json.loads(encoded) == consumer_rule_pattern(consumer)
