"""Structural tests for the per-queue DLQs, redrive policies, and alarms (task 6.3).

Same posture as `test_terraform_consumers.py`: text-structural, because CI has no
AWS credentials and no Terraform binary. The properties checked are the ones that
would otherwise surface only at an apply — a consumer queue with no dead-letter
destination, a redrive policy pointing at another consumer's DLQ, a DLQ any queue
can redrive into, or a DLQ whose depth no monitor watches (spec: "Dead-letter
volume is observable", per consumer).
"""

from __future__ import annotations

import re
from pathlib import Path

#: `packages/ocean`, from `packages/ocean/libs/ocean-broker/tests/`.
_REPO_OCEAN = Path(__file__).resolve().parents[3]
_BUS_MODULE = _REPO_OCEAN / "infra" / "terraform" / "modules" / "eventbridge-ocean"


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


class TestDlqFileShape:
    """One DLQ, one redrive policy, one redrive-allow policy, one alarm — per consumer."""

    def test_dlq_file_exists(self):
        assert (_BUS_MODULE / "dlq.tf").is_file()

    def test_declares_exactly_one_of_each_resource(self):
        code = _code_only(_tf_text("dlq.tf"))

        for resource in (
            "aws_sqs_queue",
            "aws_sqs_queue_redrive_policy",
            "aws_sqs_queue_redrive_allow_policy",
            "aws_cloudwatch_metric_alarm",
        ):
            declarations = re.findall(rf'resource "{resource}" ', code)
            assert len(declarations) == 1, f"expected exactly one {resource}, found {len(declarations)}"

    def test_every_resource_fans_out_over_the_generated_patterns(self):
        code = _code_only(_tf_text("dlq.tf"))

        assert code.count("for_each") == 4
        assert code.count("var.consumer_rule_patterns") >= 1

    def test_consumers_file_is_untouched_by_the_dlq(self):
        """6.2's queue declares no redrive of its own; the standalone resource owns it."""
        code = _code_only(_tf_text("consumers.tf"))

        assert "redrive_policy" not in code
        assert "dlq" not in code.lower()


class TestDlqShape:
    """A standard queue named after its consumer, retaining messages the SQS maximum."""

    def _dlq(self) -> str:
        return _block(_code_only(_tf_text("dlq.tf")), 'resource "aws_sqs_queue"')

    def test_dlq_is_not_fifo(self):
        assert "fifo_queue" not in self._dlq()

    def test_dlq_name_carries_the_bus_name_the_consumer_and_a_dlq_suffix(self):
        assert re.search(
            r'^\s*name\s*=\s*"\$\{var\.event_bus_name\}-\$\{each\.key\}-dlq"\s*$',
            self._dlq(),
            re.MULTILINE,
        )

    def test_dlq_retention_is_the_configured_variable(self):
        assert "var.dlq_message_retention_seconds" in self._dlq()


class TestRedrivePolicy:
    """Each consumer queue dead-letters into its own DLQ after the configured attempts."""

    def _redrive(self) -> str:
        return _block(_code_only(_tf_text("dlq.tf")), 'resource "aws_sqs_queue_redrive_policy"')

    def test_attaches_to_the_consumer_queue(self):
        assert "aws_sqs_queue.consumer[each.key].id" in self._redrive()

    def test_targets_this_consumers_own_dlq(self):
        assert "aws_sqs_queue.dlq[each.key].arn" in self._redrive()

    def test_max_receive_count_is_the_configured_variable(self):
        assert "var.dlq_max_receive_count" in self._redrive()


class TestRedriveAllowPolicy:
    """Only this consumer's own queue may use the DLQ as its dead-letter target."""

    def _allow(self) -> str:
        return _block(_code_only(_tf_text("dlq.tf")), 'resource "aws_sqs_queue_redrive_allow_policy"')

    def test_attaches_to_the_dlq(self):
        assert "aws_sqs_queue.dlq[each.key].id" in self._allow()

    def test_permits_only_the_source_queue(self):
        allow = self._allow()

        assert '"byQueue"' in allow
        assert "aws_sqs_queue.consumer[each.key].arn" in allow


class TestDlqDepthAlarm:
    """Spec scenario: a message landing in a DLQ is visible to monitoring, per consumer."""

    def _alarm(self) -> str:
        return _block(_code_only(_tf_text("dlq.tf")), 'resource "aws_cloudwatch_metric_alarm"')

    def test_watches_visible_messages_on_the_sqs_namespace(self):
        alarm = self._alarm()

        assert '"AWS/SQS"' in alarm
        assert '"ApproximateNumberOfMessagesVisible"' in alarm

    def test_dimension_is_this_consumers_dlq(self):
        assert "aws_sqs_queue.dlq[each.key].name" in self._alarm()

    def test_fires_on_a_single_dead_letter(self):
        """Depth >= 1 alarms: one stuck event is a consumer failure in progress."""
        alarm = self._alarm()

        assert re.search(r"^\s*threshold\s*=\s*0\s*$", alarm, re.MULTILINE)
        assert '"GreaterThanThreshold"' in alarm

    def test_an_empty_dlq_is_healthy_not_missing(self):
        alarm = self._alarm()

        assert re.search(r'^\s*treat_missing_data\s*=\s*"notBreaching"\s*$', alarm, re.MULTILINE)

    def test_notifications_route_to_the_configured_actions(self):
        alarm = self._alarm()

        assert "var.dlq_alarm_actions" in alarm
        assert "ok_actions" in alarm


class TestModuleInterface:
    """What the environment config and monitoring consume."""

    def test_dlq_max_receive_count_is_declared_with_a_bounded_default(self):
        variable = _block(_code_only(_tf_text("variables.tf")), 'variable "dlq_max_receive_count"')

        assert "number" in variable
        assert "validation" in variable

    def test_dlq_retention_is_declared(self):
        variable = _block(_code_only(_tf_text("variables.tf")), 'variable "dlq_message_retention_seconds"')

        assert "number" in variable

    def test_alarm_actions_default_to_none_rather_than_a_baked_in_topic(self):
        variable = _block(_code_only(_tf_text("variables.tf")), 'variable "dlq_alarm_actions"')

        assert "list(string)" in variable
        assert re.search(r"^\s*default\s*=\s*\[\]\s*$", variable, re.MULTILINE)

    def test_outputs_expose_dlqs_and_alarms_per_consumer(self):
        outputs = _tf_text("outputs.tf")

        for name in ("consumer_dlq_urls", "consumer_dlq_arns", "consumer_dlq_alarm_arns"):
            assert f'output "{name}"' in outputs
