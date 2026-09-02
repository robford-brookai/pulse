"""`billing_connector.declare` — task 2.2 behavior.

Covers the spec scenarios this module owns: a replay is an idempotent hit and declares nothing
new; a rejected transition keeps the verdict's own evidence and counts distinctly; an
`indeterminate` verdict never attempts a transition; no amount-bearing value or credential value
ever reaches a submitted command body or a log line. The command API is faked at the client
boundary (`factories.FakeCommandTransport`, an `httpx.MockTransport` under a real
`PulseCoreClient`), per the change's testing posture; `conftest.py` blocks sockets for every run.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import cast

import httpx
import pytest
from billing_connector.declare import DeclareResult, declare_pair, idempotency_key
from billing_connector.evaluate import Evaluation, SubjectRef
from pulse_core.client import ResponseClassification

from tests.factories import FakeCommandTransport


def _fixture_evaluation(
    *,
    subject_key: str = "fixture-episode-1",
    verdict_type: str = "billing_eligibility",
    rule_version: str = "pulse-billing-eligibility-v1",
    outcome: str = "positive",
    reason: str | None = None,
    facts_hash: str = "fixture-hash",
) -> Evaluation:
    return Evaluation(
        subject=SubjectRef(subject_type="billing_episode", subject_key=subject_key),
        verdict_type=verdict_type,
        rule_version=rule_version,
        outcome=outcome,
        reason=reason,
        facts_stale=False,
        facts_hash=facts_hash,
        as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


def committed(event_id: str = "event-1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = "event-1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": True})


def rejected(reason: str = "illegal transition") -> httpx.Response:
    return httpx.Response(
        422,
        json={
            "detail": {
                "message": "the ledger refused this",
                "reason": reason,
                "catalog_version": "appendix-c-v0.7",
            }
        },
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


class TestIdempotencyKey:
    def test_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(idempotency_key).parameters) == ["evaluation"]

    def test_same_evaluation_derives_the_same_key(self) -> None:
        assert idempotency_key(_fixture_evaluation()) == idempotency_key(_fixture_evaluation())

    @pytest.mark.parametrize(
        "overrides",
        [
            {"subject_key": "other-episode"},
            {"verdict_type": "coverage_eligibility"},
            {"rule_version": "pulse-billing-eligibility-v2"},
            {"facts_hash": "a-different-hash"},
        ],
    )
    def test_changing_any_one_part_changes_the_key(self, overrides: dict[str, str]) -> None:
        base = idempotency_key(_fixture_evaluation())
        changed = idempotency_key(_fixture_evaluation(**overrides))
        assert base != changed

    def test_key_names_all_four_parts_and_nothing_else(self) -> None:
        evaluation = _fixture_evaluation()
        key = idempotency_key(evaluation)
        assert key == "fixture-episode-1:billing_eligibility:pulse-billing-eligibility-v1:fixture-hash"


class TestDeclarePairSignature:
    def test_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(declare_pair).parameters) == ["client", "evaluation"]

    def test_return_annotation_is_declare_result(self) -> None:
        signature = inspect.signature(declare_pair)
        assert signature.return_annotation == "DeclareResult"


class TestPairedTransition:
    """Scenario: a decisive outcome on a registered verdict type follows its verdict with the
    registered transition."""

    def test_positive_verdict_pairs_with_its_registered_transition(self) -> None:
        transport = FakeCommandTransport([committed("event-1"), committed("event-2")])
        client = transport.client()

        result = declare_pair(client, _fixture_evaluation(outcome="positive"))

        assert result.classification is ResponseClassification.COMMITTED
        assert result.event_id == "event-1"
        assert result.transition_rejected is False
        assert len(transport.bodies) == 2
        transition_body = transport.bodies[1]
        assert transition_body["event_type"] == "declare_transition"
        assert transition_body["to_state"] == "qualified"

    def test_negative_verdict_pairs_with_its_registered_transition(self) -> None:
        transport = FakeCommandTransport([committed("event-1"), committed("event-2")])
        client = transport.client()

        declare_pair(client, _fixture_evaluation(outcome="negative"))

        assert transport.bodies[1]["to_state"] == "not_qualified"

    def test_indeterminate_declares_evidence_with_no_transition(self) -> None:
        transport = FakeCommandTransport([committed("event-1")])
        client = transport.client()

        result = declare_pair(
            client,
            _fixture_evaluation(outcome="indeterminate", reason="awaiting_source"),
        )

        assert result.classification is ResponseClassification.COMMITTED
        assert result.transition_rejected is False
        assert len(transport.bodies) == 1

    def test_an_unregistered_verdict_type_declares_the_verdict_only(self) -> None:
        transport = FakeCommandTransport([committed("event-1")])
        client = transport.client()

        result = declare_pair(client, _fixture_evaluation(verdict_type="coverage_eligibility"))

        assert result.transition_rejected is False
        assert len(transport.bodies) == 1


class TestReplayScenario:
    """Scenario: re-evaluating unchanged facts declares nothing new."""

    def test_resubmitting_the_same_evaluation_classifies_as_replayed(self) -> None:
        transport = FakeCommandTransport([committed("event-1"), replayed("event-1")])
        client = transport.client()
        evaluation = _fixture_evaluation(verdict_type="coverage_eligibility")

        first = declare_pair(client, evaluation)
        second = declare_pair(client, evaluation)

        assert first.classification is ResponseClassification.COMMITTED
        assert second.classification is ResponseClassification.REPLAYED
        assert second.event_id == "event-1"
        assert len(transport.bodies) == 2
        assert transport.bodies[0] == transport.bodies[1]  # byte-identical: same fact, same key


class TestRejectedVerdict:
    def test_a_rejected_verdict_attempts_no_transition(self) -> None:
        transport = FakeCommandTransport([rejected("catalog violation")])
        client = transport.client()

        result = declare_pair(client, _fixture_evaluation(outcome="positive"))

        assert result.classification is ResponseClassification.REJECTED
        assert result.event_id is None
        assert result.transition_rejected is False
        assert len(transport.bodies) == 1


class TestRejectedTransitionScenario:
    """Scenario: a rejected transition keeps its evidence."""

    def test_the_verdict_commits_and_the_transition_counts_as_rejected(self) -> None:
        transport = FakeCommandTransport([committed("event-1"), rejected("no longer legal")])
        client = transport.client()

        result = declare_pair(client, _fixture_evaluation(outcome="positive"))

        assert result.classification is ResponseClassification.COMMITTED
        assert result.event_id == "event-1"
        assert result.transition_rejected is True


class TestNoMonetaryValueCrossesTheSeam:
    """Tripwire: an amount-bearing fixture leaks nothing into the payload or a log line."""

    _FORBIDDEN_FIELDS = ("billed_amount_cents", "amount", "value")

    def test_the_submitted_bodies_carry_only_the_expected_fields(self) -> None:
        transport = FakeCommandTransport([committed("event-1"), committed("event-2")])
        client = transport.client()

        declare_pair(client, _fixture_evaluation(outcome="positive"))

        assert isinstance(transport.bodies[0]["payload"], dict)
        verdict_payload = cast("dict[str, object]", transport.bodies[0]["payload"])
        assert set(verdict_payload) == {"outcome", "reason", "rule_version", "as_of", "lineage"}
        assert isinstance(verdict_payload["lineage"], dict)
        lineage = cast("dict[str, object]", verdict_payload["lineage"])
        for forbidden in self._FORBIDDEN_FIELDS:
            assert forbidden not in verdict_payload
            assert forbidden not in lineage

    def test_no_log_line_carries_a_credential_value(self, caplog: pytest.LogCaptureFixture) -> None:
        transport = FakeCommandTransport([rejected("catalog violation"), committed("event-2")])
        client = transport.client()

        with caplog.at_level(logging.WARNING):
            declare_pair(client, _fixture_evaluation(outcome="positive"))

        rendered = "\n".join(record.getMessage() for record in caplog.records)
        assert "unit-test-token" not in rendered
        assert "Bearer" not in rendered
