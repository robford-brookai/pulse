"""Unit tests for ocean_broker.catalog — the topic → (source, detail-type) surface.

Covers the `event-transport` requirement "Topic addressing is a single generated
mapping": one table, two derived surfaces (publisher addressing and Terraform rule
patterns), and no way for the two to drift.

Every assertion here runs without the local stack — pattern matching is evaluated
against the same table the patterns are emitted from.
"""

from __future__ import annotations

import json

import pytest
from ocean_broker.catalog import (
    EVENT_SOURCE,
    LIVE_DOMAINS,
    RETIRED_DOMAINS,
    TOPIC_PREFIX,
    EventBridgeAddress,
    address_for,
    addressing_table,
    domain_for_topic,
    pattern_matches,
    render_tfvars_json,
    rule_pattern,
    tfvars_path,
)

# The eleven live domains, transcribed from design D1 rather than imported, so the
# table cannot silently drift away from the design it implements.
DESIGN_D1_DOMAINS = {
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
}


class TestSourceTable:
    """The table itself: eleven live domains, warehouse-dlq retired."""

    def test_exactly_the_eleven_design_domains(self):
        assert set(LIVE_DOMAINS) == DESIGN_D1_DOMAINS
        assert len(LIVE_DOMAINS) == 11

    def test_no_duplicate_entries(self):
        assert len(set(LIVE_DOMAINS)) == len(LIVE_DOMAINS)

    def test_warehouse_dlq_is_retired_and_absent(self):
        assert "warehouse-dlq" not in LIVE_DOMAINS
        assert "warehouse-dlq" in RETIRED_DOMAINS


class TestTopicTranslation:
    """`domain_for_topic` — the one shared naming adapter for legacy call sites.

    Hoisted here from per-service copies (task 4.14): every publish site that still
    names its destination `ocean.<domain>` translates through this single function.
    """

    @pytest.mark.parametrize("domain", sorted(LIVE_DOMAINS))
    def test_legacy_topic_maps_to_its_domain(self, domain):
        assert domain_for_topic(f"{TOPIC_PREFIX}{domain}") == domain

    @pytest.mark.parametrize("domain", sorted(LIVE_DOMAINS))
    def test_bare_domain_passes_through(self, domain):
        assert domain_for_topic(domain) == domain

    def test_retired_topic_is_rejected_before_the_bus(self):
        with pytest.raises(KeyError):
            domain_for_topic("ocean.warehouse-dlq")

    def test_unknown_topic_is_rejected_before_the_bus(self):
        with pytest.raises(KeyError):
            domain_for_topic("ocean.no-such-domain")

    def test_prefix_matches_the_retired_topic_namespace(self):
        """Every kafka_topic in the table is TOPIC_PREFIX + domain, so translation round-trips."""
        for domain in LIVE_DOMAINS:
            assert domain_for_topic(address_for(domain).kafka_topic) == domain


class TestPublisherAddressing:
    """Surface one: what a publisher puts on the wire."""

    @pytest.mark.parametrize("domain", LIVE_DOMAINS)
    def test_every_domain_maps_to_constant_source_and_itself_as_detail_type(self, domain):
        address = address_for(domain)

        assert address.source == EVENT_SOURCE == "ocean"
        assert address.detail_type == domain

    @pytest.mark.parametrize("domain", LIVE_DOMAINS)
    def test_kafka_topic_round_trips(self, domain):
        assert address_for(domain).kafka_topic == f"ocean.{domain}"

    def test_addressing_table_has_one_entry_per_live_domain(self):
        table = addressing_table()

        assert set(table) == set(LIVE_DOMAINS)
        assert len(table) == len(LIVE_DOMAINS)

    def test_address_is_immutable(self):
        address = address_for("signals")

        with pytest.raises(AttributeError):
            address.detail_type = "alerts"  # type: ignore[misc]

    def test_addressing_table_mutation_does_not_leak_into_the_catalog(self):
        addressing_table()["signals"] = EventBridgeAddress(source="x", detail_type="y")

        assert address_for("signals") == EventBridgeAddress(source="ocean", detail_type="signals")

    def test_retired_domain_cannot_be_addressed(self):
        with pytest.raises(KeyError):
            address_for("warehouse-dlq")

    def test_unknown_domain_cannot_be_addressed(self):
        with pytest.raises(KeyError):
            address_for("not-a-domain")


class TestRulePatterns:
    """Surface two: what a Terraform rule matches on."""

    @pytest.mark.parametrize("domain", LIVE_DOMAINS)
    def test_single_domain_pattern_matches_exactly_that_domain(self, domain):
        pattern = rule_pattern([domain])

        assert pattern_matches(pattern, EVENT_SOURCE, domain)
        for other in LIVE_DOMAINS:
            if other != domain:
                assert not pattern_matches(pattern, EVENT_SOURCE, other)

    def test_multi_domain_pattern_matches_its_whole_set_and_nothing_else(self):
        consumer_domains = ["signals", "alerts", "outcomes"]
        pattern = rule_pattern(consumer_domains)

        for domain in LIVE_DOMAINS:
            expected = domain in consumer_domains
            assert pattern_matches(pattern, EVENT_SOURCE, domain) is expected

    def test_pattern_does_not_match_a_foreign_source(self):
        pattern = rule_pattern(["signals"])

        assert not pattern_matches(pattern, "not-ocean", "signals")

    def test_pattern_keys_are_deterministic_and_sorted(self):
        assert rule_pattern(["tickets", "alerts", "alerts"]) == {
            "source": ["ocean"],
            "detail-type": ["alerts", "tickets"],
        }

    def test_pattern_constrains_nothing_beyond_source_and_detail_type(self):
        """A new event_type inside an existing domain must need no rule edit."""
        pattern = rule_pattern(["signals"])

        assert set(pattern) == {"source", "detail-type"}

    def test_retired_domain_has_no_pattern(self):
        with pytest.raises(KeyError):
            rule_pattern(["warehouse-dlq"])

    def test_empty_domain_set_is_rejected(self):
        with pytest.raises(ValueError):
            rule_pattern([])


class TestSurfacesCannotDrift:
    """The point of the single table: neither surface can address what the other cannot."""

    def test_every_emitted_pattern_round_trips_against_the_table(self):
        for domain, address in addressing_table().items():
            pattern = rule_pattern([domain])

            assert pattern_matches(pattern, address.source, address.detail_type)

    def test_every_publishable_detail_type_is_matched_by_some_rule(self):
        patterns = [rule_pattern([domain]) for domain in LIVE_DOMAINS]

        for address in addressing_table().values():
            assert any(pattern_matches(p, address.source, address.detail_type) for p in patterns)

    def test_every_matchable_detail_type_is_one_a_publisher_can_emit(self):
        publishable = {a.detail_type for a in addressing_table().values()}
        matchable = {detail_type for domain in LIVE_DOMAINS for detail_type in rule_pattern([domain])["detail-type"]}

        assert matchable == publishable


class TestGeneratedTerraformInput:
    """The emitted artifact Terraform consumes, and its drift guard."""

    def test_committed_tfvars_matches_regeneration(self):
        committed = tfvars_path().read_text()

        assert committed == render_tfvars_json(), (
            "infra/terraform/generated/event_catalog.auto.tfvars.json is stale — "
            "run `uv run python scripts/generate_event_catalog.py`"
        )

    def test_tfvars_exposes_the_table_and_one_pattern_per_domain(self):
        emitted = json.loads(render_tfvars_json())

        assert emitted["event_source"] == EVENT_SOURCE
        assert emitted["event_domains"] == sorted(LIVE_DOMAINS)
        assert set(emitted["domain_event_patterns"]) == set(LIVE_DOMAINS)

    def test_tfvars_patterns_are_json_strings_terraform_can_pass_through(self):
        emitted = json.loads(render_tfvars_json())

        for domain, encoded in emitted["domain_event_patterns"].items():
            assert isinstance(encoded, str)
            assert json.loads(encoded) == rule_pattern([domain])

    def test_tfvars_ends_with_a_newline(self):
        assert render_tfvars_json().endswith("\n")
