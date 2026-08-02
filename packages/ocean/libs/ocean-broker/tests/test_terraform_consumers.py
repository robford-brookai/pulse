"""Structural tests for the per-consumer rules and queues (task 6.2).

Same posture as `test_terraform_bus.py`: text-structural, because CI has no AWS
credentials and no Terraform binary. The properties checked are the ones that
would otherwise surface only at an apply — a rule that hand-writes its pattern
instead of taking the generated one, a queue another service can write to, a
target pointed at the wrong bus, or a FIFO queue sneaking in against design D3.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ocean_broker.catalog import CONSUMER_DOMAINS

#: `packages/ocean`, from `packages/ocean/libs/ocean-broker/tests/`.
_REPO_OCEAN = Path(__file__).resolve().parents[3]
_TERRAFORM = _REPO_OCEAN / "infra" / "terraform"
_BUS_MODULE = _TERRAFORM / "modules" / "eventbridge-ocean"


def _tf_text(name: str) -> str:
    return (_BUS_MODULE / name).read_text()


def _code_only(text: str) -> str:
    """Drop comment lines, so prose about the design is not read as configuration."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _block(text: str, header: str) -> str:
    """Return the body of the first brace-balanced block whose header line matches."""
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


class TestConsumersFileShape:
    """One rule, one queue, one target, one queue policy — each fanned over the registry."""

    def test_consumers_file_exists(self):
        assert (_BUS_MODULE / "consumers.tf").is_file()

    def test_declares_exactly_one_of_each_resource(self):
        code = _code_only(_tf_text("consumers.tf"))

        for resource in (
            "aws_cloudwatch_event_rule",
            "aws_sqs_queue",
            "aws_cloudwatch_event_target",
            "aws_sqs_queue_policy",
        ):
            declarations = re.findall(rf'resource "{resource}" ', code)
            assert len(declarations) == 1, f"expected exactly one {resource}, found {len(declarations)}"

    def test_every_resource_fans_out_over_the_generated_patterns(self):
        code = _code_only(_tf_text("consumers.tf"))

        assert code.count("for_each") == 4
        assert code.count("var.consumer_rule_patterns") >= 1


class TestRuleTakesTheGeneratedPatternOnly:
    """The pattern is pass-through from the catalog; the module writes none of it."""

    def test_rule_pattern_is_the_generated_value_verbatim(self):
        rule = _block(_code_only(_tf_text("consumers.tf")), 'resource "aws_cloudwatch_event_rule"')

        assert re.search(r"^\s*event_pattern\s*=\s*each\.value\s*$", rule, re.MULTILINE)

    def test_rule_attaches_to_the_ocean_bus(self):
        rule = _block(_code_only(_tf_text("consumers.tf")), 'resource "aws_cloudwatch_event_rule"')

        assert "aws_cloudwatch_event_bus.ocean.name" in rule

    def test_target_is_on_the_same_bus_and_points_at_the_consumer_queue(self):
        target = _block(_code_only(_tf_text("consumers.tf")), 'resource "aws_cloudwatch_event_target"')

        assert "aws_cloudwatch_event_bus.ocean.name" in target
        assert "aws_cloudwatch_event_rule.consumer" in target
        assert "aws_sqs_queue.consumer" in target


class TestQueueShape:
    """Standard queues: design D3 rejected FIFO on a platform constraint."""

    def test_queue_is_not_fifo(self):
        queue = _block(_code_only(_tf_text("consumers.tf")), 'resource "aws_sqs_queue"')

        assert "fifo_queue" not in queue

    def test_queue_name_carries_the_bus_name_and_the_consumer(self):
        queue = _block(_code_only(_tf_text("consumers.tf")), 'resource "aws_sqs_queue"')

        assert re.search(r'^\s*name\s*=\s*"\$\{var\.event_bus_name\}-\$\{each\.key\}"\s*$', queue, re.MULTILINE)


class TestQueuePolicyScope:
    """Only EventBridge, only SendMessage, only via this consumer's own rule."""

    def _policy(self) -> str:
        return _block(_code_only(_tf_text("consumers.tf")), 'resource "aws_sqs_queue_policy"')

    def test_grants_only_send_message(self):
        actions = re.findall(r'"(sqs:[A-Za-z*]+)"', self._policy())

        assert actions == ["sqs:SendMessage"]

    def test_principal_is_eventbridge(self):
        assert "events.amazonaws.com" in self._policy()

    def test_is_conditioned_on_this_consumers_rule(self):
        policy = self._policy()

        assert "ArnEquals" in policy
        assert "aws:SourceArn" in policy
        assert "aws_cloudwatch_event_rule.consumer[each.key].arn" in policy


class TestModuleInterface:
    """What 6.3 (DLQs), 6.5 (LocalStack) and the EKS env config consume."""

    def test_consumer_rule_patterns_variable_is_declared_without_a_default(self):
        variable = _block(_code_only(_tf_text("variables.tf")), 'variable "consumer_rule_patterns"')

        assert "map(string)" in variable
        assert "default" not in variable, "patterns must come from the generated tfvars, never a baked-in copy"

    def test_outputs_expose_queues_and_rules_per_consumer(self):
        outputs = _tf_text("outputs.tf")

        for name in ("consumer_queue_urls", "consumer_queue_arns", "consumer_rule_arns"):
            assert f'output "{name}"' in outputs


class TestGeneratedTfvarsCarriesTheConsumerPatterns:
    """The committed artifact Terraform auto-loads matches the registry."""

    def test_committed_tfvars_has_one_pattern_per_consumer(self):
        generated = json.loads((_TERRAFORM / "generated" / "event_catalog.auto.tfvars.json").read_text())

        assert set(generated["consumer_rule_patterns"]) == set(CONSUMER_DOMAINS)
