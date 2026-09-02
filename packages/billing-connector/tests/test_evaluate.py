"""`billing_connector.evaluate` — task 1.3 scaffold stub.

Behavior lands in task 2.1; this module only pins the public shape: `Evaluation`'s fields,
`evaluate_subject`'s signature, and that its body is not yet implemented.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from billing_connector.evaluate import Evaluation, SubjectRef, evaluate_subject


class TestEvaluationShape:
    def test_evaluation_carries_exactly_the_declared_fields(self) -> None:
        evaluation = Evaluation(
            subject=SubjectRef(subject_type="billing_episode", subject_key="fixture-episode-1"),
            verdict_type="billing_eligibility",
            rule_version="pulse-billing-eligibility-v1",
            outcome="indeterminate",
            reason="period_open",
            facts_stale=False,
            facts_hash="fixture-hash",
            as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )

        assert evaluation.verdict_type == "billing_eligibility"
        assert evaluation.reason == "period_open"

    def test_evaluation_is_frozen(self) -> None:
        evaluation = Evaluation(
            subject=SubjectRef(subject_type="billing_episode", subject_key="fixture-episode-1"),
            verdict_type="billing_eligibility",
            rule_version="pulse-billing-eligibility-v1",
            outcome="positive",
            reason=None,
            facts_stale=False,
            facts_hash="fixture-hash",
            as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )

        with pytest.raises(AttributeError):
            evaluation.outcome = "negative"  # type: ignore[misc]


class TestEvaluateSubjectSignature:
    def test_signature_matches_the_work_order(self) -> None:
        parameters = list(inspect.signature(evaluate_subject).parameters)
        assert parameters == ["store", "registry", "config", "subject"]

    def test_return_annotation_is_a_list_of_evaluation(self) -> None:
        signature = inspect.signature(evaluate_subject)
        assert signature.return_annotation == "list[Evaluation]"

    def test_body_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            evaluate_subject(
                store=object(),
                registry={},
                config=object(),  # type: ignore[arg-type]
                subject=SubjectRef(subject_type="billing_episode", subject_key="fixture-episode-1"),
            )
