"""Structural tests for the EventBridge bus Terraform module (task 6.1).

These live beside the broker's tests, next to `test_catalog.py`, for the same reason
that one reads `infra/redpanda/topics.sh`: the bus is the other half of
`EventBridgePublisher`'s contract, and `packages/ocean/libs` is what `task test`
collects. A test under `infra/` would not run in CI.

They are text-structural rather than a `terraform plan`: CI has no AWS credentials,
no network, and no Terraform binary, so the properties checked here are the ones
that can be wrong without anyone noticing until an apply — the bus name drifting
away from the publisher's default, the publish permission widening to `*`, or a
Kafka resource surviving the migration. `terraform fmt` is checked too, but only
where the binary exists.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from ocean_broker.publisher import _DEFAULT_EVENT_BUS

#: `packages/ocean`, from `packages/ocean/libs/ocean-broker/tests/`.
_REPO_OCEAN = Path(__file__).resolve().parents[3]
_TERRAFORM = _REPO_OCEAN / "infra" / "terraform"
_BUS_MODULE = _TERRAFORM / "modules" / "eventbridge-ocean"


def _tf_text(name: str) -> str:
    return (_BUS_MODULE / name).read_text()


def _code_only(text: str) -> str:
    """Drop comment lines, so prose about the migration is not read as configuration.

    A module that explains what it replaced is worth more than one that pretends
    Kafka never existed; only the resources are the claim under test.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _block(text: str, header: str) -> str:
    """Return the body of the first brace-balanced block whose header line matches.

    A brace count is enough for HCL here: the module's strings contain no braces
    outside `jsonencode`, which is itself balanced.
    """
    start = text.index(header)
    depth = 0
    for offset in range(start, len(text)):
        if text[offset] == "{":
            depth += 1
        elif text[offset] == "}":
            depth -= 1
            if depth == 0:
                return text[start : offset + 1]
    raise AssertionError(f"unterminated block for {header!r}")


class TestMskIsGone:
    """The Kafka module is deleted, not merely unused."""

    def test_msk_module_directory_is_removed(self):
        assert not (_TERRAFORM / "modules" / "msk-ocean").exists()

    def test_no_terraform_file_references_kafka_or_msk(self):
        offenders = [
            path.relative_to(_REPO_OCEAN)
            for path in sorted(_TERRAFORM.rglob("*.tf"))
            if re.search(r"aws_msk_|kafka", _code_only(path.read_text()), re.IGNORECASE)
        ]

        assert offenders == []


class TestBusModuleShape:
    """The replacement module exists and exposes what task 6.2's rules consume."""

    @pytest.mark.parametrize("filename", ["main.tf", "variables.tf", "outputs.tf", "iam.tf"])
    def test_module_file_exists(self, filename):
        assert (_BUS_MODULE / filename).is_file()

    def test_declares_exactly_one_event_bus(self):
        assert _tf_text("main.tf").count('resource "aws_cloudwatch_event_bus"') == 1

    def test_bus_name_comes_from_the_variable(self):
        bus = _block(_tf_text("main.tf"), 'resource "aws_cloudwatch_event_bus"')

        assert re.search(r"^\s*name\s*=\s*var\.event_bus_name\s*$", bus, re.MULTILINE)

    def test_bus_default_name_matches_the_publisher_default(self):
        """A mismatch here publishes into a bus that has no rules — accepted, then dropped."""
        variable = _block(_tf_text("variables.tf"), 'variable "event_bus_name"')
        default = re.search(r'^\s*default\s*=\s*"([^"]+)"\s*$', variable, re.MULTILINE)

        assert default is not None, "event_bus_name must state a default"
        assert default.group(1) == _DEFAULT_EVENT_BUS

    @pytest.mark.parametrize("name", ["event_bus_name", "event_bus_arn", "publisher_policy_arn"])
    def test_output_is_exposed(self, name):
        assert f'output "{name}"' in _tf_text("outputs.tf")


class TestPublisherPermission:
    """The IAM policy that replaces the deleted `kafka-cluster:*` connector policy."""

    def test_grants_only_put_events(self):
        policy = _block(_tf_text("iam.tf"), 'resource "aws_iam_policy" "publisher"')
        actions = re.findall(r'"(events:[A-Za-z*]+)"', policy)

        assert actions == ["events:PutEvents"]

    def test_is_scoped_to_this_bus(self):
        policy = _block(_tf_text("iam.tf"), 'resource "aws_iam_policy" "publisher"')

        assert "aws_cloudwatch_event_bus.ocean.arn" in policy
        assert '"*"' not in policy, "a wildcard resource lets any bus in the account be published to"


class TestGeneratedCatalogIsStillTheOnlyPatternSource:
    """6.1 adds the bus only: patterns arrive with the rules in 6.2, from the catalog."""

    def test_module_hand_writes_no_event_pattern(self):
        for path in sorted(_BUS_MODULE.glob("*.tf")):
            assert "detail-type" not in _code_only(path.read_text())

    def test_generated_tfvars_survives_the_module_swap(self):
        generated = json.loads((_TERRAFORM / "generated" / "event_catalog.auto.tfvars.json").read_text())

        assert generated["event_source"] == "ocean"
        assert len(generated["event_domains"]) == 11


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform is not installed (CI runners have no binary)")
def test_module_is_terraform_fmt_clean():
    result = subprocess.run(  # noqa: S603
        [shutil.which("terraform") or "terraform", "fmt", "-check", "-recursive", str(_BUS_MODULE)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"needs `terraform fmt`:\n{result.stdout}{result.stderr}"
