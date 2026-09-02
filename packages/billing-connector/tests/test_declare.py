"""`billing_connector.declare` — task 1.3 scaffold stub.

Behavior lands in task 2.2; this module only pins the public shape: `DeclareResult`'s fields,
`declare_pair`'s and `idempotency_key`'s signatures, and that their bodies are not yet
implemented.
"""

from __future__ import annotations

import inspect

import pytest
from billing_connector.declare import DeclareResult, declare_pair, idempotency_key
from billing_connector.evaluate import Evaluation, SubjectRef
from pulse_core.client import ResponseClassification


def _fixture_evaluation() -> Evaluation:
    from datetime import datetime, timezone

    return Evaluation(
        subject=SubjectRef(subject_type="billing_episode", subject_key="fixture-episode-1"),
        verdict_type="billing_eligibility",
        rule_version="pulse-billing-eligibility-v1",
        outcome="positive",
        reason=None,
        facts_stale=False,
        facts_hash="fixture-hash",
        as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


class TestDeclareResultShape:
    def test_declare_result_carries_exactly_the_declared_fields(self) -> None:
        result = DeclareResult(
            classification=ResponseClassification.COMMITTED,
            event_id="fixture-event-1",
            transition_rejected=False,
        )

        assert result.classification is ResponseClassification.COMMITTED
        assert result.event_id == "fixture-event-1"
        assert result.transition_rejected is False

    def test_declare_result_is_frozen(self) -> None:
        result = DeclareResult(
            classification=ResponseClassification.REPLAYED,
            event_id=None,
            transition_rejected=False,
        )

        with pytest.raises(AttributeError):
            result.event_id = "changed"  # type: ignore[misc]


class TestIdempotencyKeySignature:
    def test_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(idempotency_key).parameters) == ["evaluation"]

    def test_body_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            idempotency_key(_fixture_evaluation())


class TestDeclarePairSignature:
    def test_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(declare_pair).parameters) == ["client", "evaluation"]

    def test_return_annotation_is_declare_result(self) -> None:
        signature = inspect.signature(declare_pair)
        assert signature.return_annotation == "DeclareResult"

    def test_body_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            declare_pair(client=object(), evaluation=_fixture_evaluation())  # type: ignore[arg-type]
