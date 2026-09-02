"""`billing_connector.evaluate` — task 2.1.

Behavior tests per tasks.md's own list: fresh vs stale vs no-row fixtures; one registered type →
one evaluation; registry mismatch halts; unchanged facts produce an identical evaluation (same
hash); no monetary value in any evaluation row (tripwire). `_FakeStore` stands in for
`billing.store.PostgresFactStore`'s new `load_snapshot` read path — no Postgres, no socket.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import timedelta
from types import ModuleType

import pytest
from billing.rules import billing_eligibility
from billing_connector.config import Config
from billing_connector.evaluate import (
    Evaluation,
    RegistryMismatchError,
    SubjectRef,
    evaluate_subject,
)

from tests.factories import make_facts, make_stale_facts


class _FakeStore:
    """Stands in for `billing.store.PostgresFactStore.load_snapshot` — the one read
    `evaluate_subject` performs, with no Postgres connection behind it."""

    def __init__(self, snapshot: object | None) -> None:
        self._snapshot = snapshot

    def load_snapshot(self, subject_type: str, subject_key: str) -> object | None:
        return self._snapshot


def _config(stale_after: timedelta = timedelta(hours=24)) -> Config:
    return Config(
        credential_name="BILLING_CONNECTOR_TOKEN",
        queue_url="https://queue.test",
        ledger_base_url="https://ledger.test",
        stale_after=stale_after,
    )


_REGISTRY = {"billing_eligibility": billing_eligibility}
_SUBJECT = SubjectRef(subject_type="billing_episode", subject_key="episode-1")


class TestEvaluationShape:
    def test_evaluation_carries_exactly_the_declared_fields(self) -> None:
        from datetime import datetime, timezone

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
        from datetime import datetime, timezone

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


class TestNoRowEvaluatesAwaitingSource:
    """Spec: "A subject with no folded events SHALL evaluate as indeterminate with the
    `awaiting_source` reason.\""""

    def test_no_row_is_indeterminate_awaiting_source(self) -> None:
        evaluations = evaluate_subject(
            store=_FakeStore(None),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=_config(),
            subject=_SUBJECT,
        )

        assert len(evaluations) == 1
        (evaluation,) = evaluations
        assert evaluation.outcome == "indeterminate"
        assert evaluation.reason == "awaiting_source"
        assert evaluation.facts_stale is True


class TestStaleWatermarkYieldsAwaitingSource:
    """Spec scenario: "A stale watermark yields awaiting_source.\""""

    def test_stale_watermark_is_indeterminate_awaiting_source(self) -> None:
        snapshot = make_stale_facts(
            subject_type="billing_episode",
            subject_key="episode-1",
            facts={"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"},
            stale_by=timedelta(days=2),
        )

        evaluations = evaluate_subject(
            store=_FakeStore(snapshot),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=_config(stale_after=timedelta(hours=24)),
            subject=_SUBJECT,
        )

        assert len(evaluations) == 1
        (evaluation,) = evaluations
        assert evaluation.outcome == "indeterminate"
        assert evaluation.reason == "awaiting_source"
        assert evaluation.facts_stale is True


class TestFreshWatermarkEvaluatesTheRule:
    """Spec scenario: "A fresh watermark evaluates the rule.\""""

    def test_fresh_watermark_runs_the_registered_rule(self) -> None:
        snapshot = make_facts(
            subject_type="billing_episode",
            subject_key="episode-1",
            facts={"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"},
        )

        evaluations = evaluate_subject(
            store=_FakeStore(snapshot),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=_config(stale_after=timedelta(hours=24)),
            subject=_SUBJECT,
        )

        assert len(evaluations) == 1
        (evaluation,) = evaluations
        assert evaluation.outcome == "positive"
        assert evaluation.reason is None
        assert evaluation.facts_stale is False
        assert evaluation.rule_version == billing_eligibility.RULE_VERSION
        assert evaluation.verdict_type == "billing_eligibility"


class TestOneRegisteredTypeOneEvaluation:
    """Spec scenario: "One registered type, one evaluation.\""""

    def test_only_the_registered_type_is_named(self) -> None:
        snapshot = make_facts(
            facts={"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"},
        )

        evaluations = evaluate_subject(
            store=_FakeStore(snapshot),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=_config(),
            subject=_SUBJECT,
        )

        assert [evaluation.verdict_type for evaluation in evaluations] == ["billing_eligibility"]

    def test_a_subject_type_with_no_registered_module_evaluates_nothing(self) -> None:
        unmatched_subject = SubjectRef(subject_type="coverage", subject_key="coverage-1")

        evaluations = evaluate_subject(
            store=_FakeStore(None),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=_config(),
            subject=unmatched_subject,
        )

        assert evaluations == []


class TestRegistryMismatchHaltsStartup:
    """Spec scenario: "A registry mismatch halts startup.\""""

    def test_a_module_missing_a_required_attribute_raises(self) -> None:
        incomplete_module = ModuleType("incomplete")
        incomplete_module.VERDICT_TYPE = "billing_eligibility"  # type: ignore[attr-defined]
        # SUBJECT_TYPE, RULE_VERSION, evaluate_from_facts are all missing.

        with pytest.raises(RegistryMismatchError):
            evaluate_subject(
                store=_FakeStore(None),  # type: ignore[arg-type]
                registry={"billing_eligibility": incomplete_module},
                config=_config(),
                subject=_SUBJECT,
            )

    def test_a_module_whose_own_verdict_type_disagrees_with_its_registry_key_raises(self) -> None:
        with pytest.raises(RegistryMismatchError):
            evaluate_subject(
                store=_FakeStore(None),  # type: ignore[arg-type]
                registry={"not_billing_eligibility": billing_eligibility},
                config=_config(),
                subject=_SUBJECT,
            )


class TestUnchangedFactsProduceAnIdenticalEvaluation:
    """Spec scenario: "Re-evaluating unchanged facts declares nothing new" — this module's own
    half of that claim is that the same facts always hash the same."""

    def test_evaluating_the_same_snapshot_twice_yields_the_same_hash(self) -> None:
        snapshot = make_facts(
            facts={"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"},
        )
        config = _config()

        (first,) = evaluate_subject(
            store=_FakeStore(snapshot),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=config,
            subject=_SUBJECT,
        )
        (second,) = evaluate_subject(
            store=_FakeStore(snapshot),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=config,
            subject=_SUBJECT,
        )

        assert first.facts_hash == second.facts_hash

    def test_a_changed_fact_changes_the_hash(self) -> None:
        unachieved = make_facts(
            facts={"period_end": "2026-08-31", "achieved": False, "consent_start": "2026-07-01"},
        )
        achieved = make_facts(
            facts={"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"},
        )
        config = _config()

        (first,) = evaluate_subject(
            store=_FakeStore(unachieved),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=config,
            subject=_SUBJECT,
        )
        (second,) = evaluate_subject(
            store=_FakeStore(achieved),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=config,
            subject=_SUBJECT,
        )

        assert first.facts_hash != second.facts_hash


class TestNoMonetaryValueCrossesTheSeam:
    """Spec: "No monetary value crosses the seam" — an amount-bearing input fact must leave no
    trace in the evaluation's own fields, only a hash."""

    def test_an_amount_bearing_fact_never_appears_in_the_evaluation(self) -> None:
        snapshot = make_facts(
            facts={
                "period_end": "2026-08-31",
                "achieved": True,
                "consent_start": "2026-07-01",
                "billed_amount_cents": 12345,
            },
        )

        (evaluation,) = evaluate_subject(
            store=_FakeStore(snapshot),  # type: ignore[arg-type]
            registry=_REGISTRY,
            config=_config(),
            subject=_SUBJECT,
        )

        for value in dataclasses.asdict(evaluation).values():
            assert value != 12345
            assert "billed_amount_cents" not in repr(value)
        assert {field.name for field in dataclasses.fields(Evaluation)} == {
            "subject",
            "verdict_type",
            "rule_version",
            "outcome",
            "reason",
            "facts_stale",
            "facts_hash",
            "as_of",
        }
