"""Tests for `schedules.sweep_registry` (task 1.1, spec: reconciliation-sweeps).

Covers the three registry-load scenarios plus the two data-model facts design decision 6 and 1
carry: the family set is derived, not hand-kept, and a `Consumer` with no `cite_field` reports
itself uncitable.
"""

from __future__ import annotations

import pytest
from pulse_core.catalog_gen import load_catalog
from schedules.sweep_registry import Consumer, UnknownOwnershipError, build_registry


class TestEveryCatalogFamilyHasExactlyOneSweepKind:
    def test_a_recorded_family_gets_the_export_diff(self) -> None:
        registry = build_registry()

        family = registry["communication_consent"]

        assert family.ownership == "recorded"
        assert family.sweep_kind == "export_diff"

    def test_a_ledger_family_gets_projection_conformance(self) -> None:
        registry = build_registry()

        family = registry["enrollment"]

        assert family.ownership == "ledger"
        assert family.sweep_kind == "projection_conformance"

    def test_an_unknown_ownership_is_refused_naming_the_family(self) -> None:
        with pytest.raises(UnknownOwnershipError) as excinfo:
            build_registry({"billing_episode": "delegated"})

        assert excinfo.value.family == "billing_episode"
        assert excinfo.value.ownership == "delegated"
        assert "billing_episode" in str(excinfo.value)
        assert "delegated" in str(excinfo.value)

    def test_no_sweep_runs_when_one_family_is_refused(self) -> None:
        with pytest.raises(UnknownOwnershipError):
            build_registry({"enrollment": "ledger", "billing_episode": "delegated"})

    def test_registry_family_set_equals_the_catalogs(self) -> None:
        registry = build_registry()

        assert set(registry) == set(load_catalog().subjects)


class TestAConsumerWithNoCiteFieldIsUncitable:
    def test_cite_field_none_marks_uncitable(self) -> None:
        consumer = Consumer(
            name="graph-projection-patients",
            families=("enrollment",),
            reader=object(),
            cite_field=None,
            freshness_budget_s=900,
            owning_change="m1-retire-patient-state",
        )

        assert consumer.uncitable is True

    def test_a_cite_field_marks_citable(self) -> None:
        consumer = Consumer(
            name="twenty-board",
            families=("enrollment",),
            reader=object(),
            cite_field="ledger_seq",
            freshness_budget_s=60,
        )

        assert consumer.uncitable is False
