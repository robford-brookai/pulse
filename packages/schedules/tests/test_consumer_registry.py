"""Tests for `schedules.consumer_registry` (task 3.2, spec: reconciliation-sweeps, design.md
decision 6): the day-one consumer registration and the registry x consumer matrix.
"""

from __future__ import annotations

from schedules.consumer_registry import (
    PATIENTS_OWNING_CHANGE,
    board_families,
    build_consumers,
    consumers_by_family,
    ledger_families,
)
from schedules.sweep_registry import Consumer, build_registry

LEDGER_FAMILIES = (
    "billing_episode",
    "consent",
    "contract",
    "coverage",
    "device",
    "enrollment",
    "referral",
)


def _consumers() -> tuple[Consumer, ...]:
    registry = build_registry()
    return build_consumers(
        registry,
        board_reader=object(),
        landing_reader=object(),
        patients_reader=object(),
    )


class TestBoardAndLedgerFamilies:
    def test_board_families_is_the_families_the_app_projects(self) -> None:
        assert board_families() == ("enrollment",)

    def test_ledger_families_excludes_the_recorded_family(self) -> None:
        registry = build_registry()

        families = ledger_families(registry)

        assert families == LEDGER_FAMILIES
        assert "communication_consent" not in families


class TestBuildConsumers:
    def test_twenty_board_covers_the_families_the_app_projects(self) -> None:
        consumers = {c.name: c for c in _consumers()}

        board = consumers["twenty-board"]

        assert board.families == ("enrollment",)
        assert board.cite_field == "ledger_seq"
        assert board.freshness_budget_s == 60
        assert board.uncitable is False

    def test_warehouse_landing_covers_every_ledger_family(self) -> None:
        consumers = {c.name: c for c in _consumers()}

        landing = consumers["warehouse-landing"]

        assert landing.families == LEDGER_FAMILIES
        assert landing.cite_field == "seq"
        assert landing.freshness_budget_s == 15 * 60

    def test_warehouse_landing_budget_is_configurable(self) -> None:
        registry = build_registry()

        consumers = build_consumers(
            registry,
            board_reader=object(),
            landing_reader=object(),
            patients_reader=object(),
            landing_freshness_budget_s=1800,
        )

        landing = next(c for c in consumers if c.name == "warehouse-landing")
        assert landing.freshness_budget_s == 1800

    def test_graph_projection_patients_is_uncitable_and_names_its_owning_change(self) -> None:
        consumers = {c.name: c for c in _consumers()}

        patients = consumers["graph-projection-patients"]

        assert patients.families == ("enrollment",)
        assert patients.uncitable is True
        assert patients.owning_change == PATIENTS_OWNING_CHANGE == "m1-retire-patient-state"


class TestConsumersByFamily:
    def test_registry_x_consumer_matrix(self) -> None:
        registry = build_registry()
        consumers = _consumers()

        matrix = consumers_by_family(consumers, ledger_families(registry))

        assert {c.name for c in matrix["enrollment"]} == {
            "twenty-board",
            "warehouse-landing",
            "graph-projection-patients",
        }
        assert {c.name for c in matrix["referral"]} == {"warehouse-landing"}

    def test_a_ledger_family_with_no_consumers_is_empty_and_passes(self) -> None:
        registry = build_registry()

        matrix = consumers_by_family((), ledger_families(registry))

        for family in LEDGER_FAMILIES:
            assert matrix[family] == ()

    def test_an_unregistered_family_is_absent_from_a_consumers_families(self) -> None:
        matrix = consumers_by_family(
            build_consumers(
                build_registry(),
                board_reader=object(),
                landing_reader=object(),
                patients_reader=object(),
            ),
            families=("enrollment", "referral"),
        )

        assert "communication_consent" not in matrix
