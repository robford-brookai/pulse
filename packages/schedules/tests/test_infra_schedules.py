"""Structural tests for the schedule-trigger Terraform module (task 5.1, spec: schedule-execution
"Schedules are wired as infrastructure config").

Text-structural rather than `terraform plan`, for the same reason
`ocean_broker`'s `test_terraform_bus.py` is: CI has no AWS credentials, no network, and may have no
Terraform binary at all. The properties checked here are the ones a hand-edit could get wrong
without anyone noticing until a deploy — a cadence drifting off D14's cron, a retry window creeping
past the same day, or a schedule silently pointed at the wrong CLI subcommand. `terraform fmt` is
checked too, but only where the binary exists.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from schedules.sweep_registry import build_registry

#: `packages/schedules`, from `packages/schedules/tests/`.
_REPO_SCHEDULES = Path(__file__).resolve().parents[1]
_TERRAFORM = _REPO_SCHEDULES / "infra" / "terraform"
_MODULE = _TERRAFORM / "modules" / "cli-schedule"
_CATALOG_PATH = _TERRAFORM / "generated" / "schedule_catalog.auto.tfvars.json"


def _tf_text(name: str) -> str:
    return (_MODULE / name).read_text()


def _code_only(text: str) -> str:
    """Drop comment lines, so prose about the design is not read as configuration (mirrors
    `ocean_broker`'s bus test — the rationale comments here name both subcommands in prose)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _catalog() -> dict[str, dict[str, object]]:
    return json.loads(_CATALOG_PATH.read_text())["schedules"]


#: The seven ledger-owned families reconcile-sweep schedules exist for (task 3.1, design decision
#: 8) — derived from the registry, never hand-listed, so this test file cannot drift from the
#: catalog the same way the production registry cannot (design decision 1).
def _ledger_families() -> set[str]:
    return {name for name, family in build_registry().items() if family.sweep_kind == "projection_conformance"}


class TestScheduleCatalog:
    """The generated tfvars is the one place cadences and targets are declared — the test that
    parses the definitions and checks both cadences and their targets (spec scenario)."""

    def test_both_jobs_have_a_schedule(self):
        assert {"month-open", "consent-sweep"} <= set(_catalog())

    def test_month_open_is_00_30_on_the_1st(self):
        assert _catalog()["month-open"]["cron_expression"] == "cron(30 0 1 * ? *)"

    def test_month_open_retry_window_stays_within_the_same_day(self):
        """A retry window past 24h could roll a retried run's `logical_time` into the next
        billing month — D14's "same-day retry window" is a hard ceiling, not a suggestion."""
        window_seconds = _catalog()["month-open"]["maximum_event_age_in_seconds"]

        assert isinstance(window_seconds, int)
        assert 0 < window_seconds <= 86400

    def test_consent_sweep_is_daily(self):
        assert _catalog()["consent-sweep"]["cron_expression"] == "rate(1 day)"

    @pytest.mark.parametrize(("name", "subcommand"), [("month-open", "month-open"), ("consent-sweep", "consent-sweep")])
    def test_each_schedule_targets_its_own_cli_subcommand(self, name: str, subcommand: str):
        assert _catalog()[name]["target_subcommand"] == subcommand


class TestReconcileSweepCatalogEntries:
    """One `reconcile-sweep-<family>` entry per ledger family, none for the recorded one (design
    decision 8, spec: "Sweeps run on a schedule"). Parity against the registry means a catalog
    release that adds or drops a ledger family is caught here, not discovered at deploy time."""

    def test_one_entry_per_ledger_family_and_none_for_the_recorded_one(self):
        catalog = _catalog()
        reconcile_entries = {name for name in catalog if name.startswith("reconcile-sweep-")}

        assert reconcile_entries == {f"reconcile-sweep-{family}" for family in _ledger_families()}
        assert "reconcile-sweep-communication_consent" not in catalog

    @pytest.mark.parametrize("family", sorted(_ledger_families()))
    def test_each_entry_is_daily(self, family: str):
        assert _catalog()[f"reconcile-sweep-{family}"]["cron_expression"] == "rate(1 day)"

    @pytest.mark.parametrize("family", sorted(_ledger_families()))
    def test_each_entry_targets_the_reconcile_sweep_subcommand(self, family: str):
        assert _catalog()[f"reconcile-sweep-{family}"]["target_subcommand"] == "reconcile-sweep"

    @pytest.mark.parametrize("family", sorted(_ledger_families()))
    def test_each_entry_names_its_own_family_as_the_argument(self, family: str):
        assert _catalog()[f"reconcile-sweep-{family}"]["target_argument"] == family

    @pytest.mark.parametrize("family", sorted(_ledger_families()))
    def test_each_entry_has_a_same_day_retry_window(self, family: str):
        window_seconds = _catalog()[f"reconcile-sweep-{family}"]["maximum_event_age_in_seconds"]

        assert isinstance(window_seconds, int)
        assert 0 < window_seconds <= 86400


class TestModuleShape:
    """The module that consumes the catalog exists and wires it, not just declares it in JSON."""

    @pytest.mark.parametrize("filename", ["main.tf", "variables.tf", "outputs.tf"])
    def test_module_file_exists(self, filename: str):
        assert (_MODULE / filename).is_file()

    def test_declares_one_schedule_per_catalog_entry(self):
        assert _tf_text("main.tf").count('resource "aws_scheduler_schedule" "job"') == 1
        assert "for_each = var.schedules" in _tf_text("main.tf")

    def test_target_command_derives_from_the_catalog_subcommand(self):
        """No hand-written `"month-open"` / `"consent-sweep"` string in the module's
        configuration: the subcommand must come from `each.value.target_subcommand`, or the
        module and the catalog can drift."""
        main = _code_only(_tf_text("main.tf"))

        assert "each.value.target_subcommand" in main
        assert '"month-open"' not in main
        assert '"consent-sweep"' not in main

    def test_target_argument_derives_from_the_catalog_and_no_family_is_hand_written(self):
        """`reconcile-sweep-<family>` entries carry their family as `target_argument`
        (task 3.1); the module must read it from `each.value`, never a hand-written family
        literal — the same drift guard `target_subcommand` gets."""
        main = _code_only(_tf_text("main.tf"))

        assert "each.value.target_argument" in main
        for family in _ledger_families():
            assert f'"{family}"' not in main

    def test_retry_policy_reads_from_the_catalog(self):
        main = _tf_text("main.tf")

        assert "each.value.maximum_retry_attempts" in main
        assert "each.value.maximum_event_age_in_seconds" in main

    @pytest.mark.parametrize("name", ["schedules", "target_arn", "role_arn"])
    def test_variable_has_no_fallback_default(self, name: str):
        """Generated/deploy-time inputs, deliberately without a default — same posture
        `consumer_rule_patterns` takes in `eventbridge-ocean`."""
        variables_tf = _tf_text("variables.tf")
        start = variables_tf.index(f'variable "{name}"')
        block = variables_tf[start : variables_tf.index("\n}", start)]

        assert "default" not in block

    @pytest.mark.parametrize("name", ["schedule_arns", "schedule_names"])
    def test_output_is_exposed(self, name: str):
        assert f'output "{name}"' in _tf_text("outputs.tf")


class TestNoHandWrittenPattern:
    """5.1 adds triggers only: the catalog is the one source of cadence and target, never a
    literal duplicated into the module (mirrors `TestGeneratedCatalogIsStillTheOnlyPatternSource`
    in `ocean_broker`'s bus test)."""

    def test_module_hand_writes_no_cron_or_rate_expression(self):
        for path in sorted(_MODULE.glob("*.tf")):
            text = path.read_text()
            assert not re.search(r"\bcron\(|\brate\(", text)


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform is not installed (CI runners have no binary)")
def test_module_is_terraform_fmt_clean():
    result = subprocess.run(  # noqa: S603
        [shutil.which("terraform") or "terraform", "fmt", "-check", "-recursive", str(_MODULE)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"needs `terraform fmt`:\n{result.stdout}{result.stderr}"
