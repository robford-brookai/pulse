"""`billing_connector.service` — task 2.3 behavior.

Covers tasks.md's own list for this task: an episode-event fixture triggers exactly the affected
subject; consent and enrollment fixtures evaluate nothing and count `deferred`; a redelivered
event evaluates once; the receipt golden; end to end through a fixture queue with sockets blocked
(`conftest.py` blocks them for every run that collects this package, `--disable-socket` or not).

Three fakes, no transports: `_FakeStore` stands in for `billing.store.PostgresFactStore` (the
fold, the evaluate-time read, and the `evaluations` append), `factories.FakeCommandTransport`
fakes the command API under a real `PulseCoreClient`, and `_FakeSqs` replays scripted queue
messages through the kit's real `consume_once`. Two recordings from `tests/fixtures/` drive their
own scenarios for real here rather than being shape-checked only.
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import httpx
import pytest
from billing.facts import SubjectFactsSnapshot
from billing.rules import billing_eligibility
from billing_connector.config import Config, MissingConfigVariableError
from billing_connector.evaluate import RegistryMismatchError
from billing_connector.receipts import Receipt
from billing_connector.service import (
    TRIGGER_SUBJECT_TYPES,
    WRITER_ID,
    main,
    resolve_registry,
    run,
    run_batch,
)

from tests.factories import FakeCommandTransport, make_facts, make_stale_facts

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_REGISTRY: dict[str, ModuleType] = {"billing_eligibility": billing_eligibility}

#: A declared event id shaped like the ledger's own (the `evaluations.declared_event_id` column is
#: a UUID) — `_FakeStore` records it verbatim, so the shape matters only for realism here.
_DECLARED_EVENT_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def _load_fixture(case: str) -> dict[str, Any]:
    with (FIXTURES_DIR / f"{case}.json").open(encoding="utf-8") as handle:
        recorded: object = json.load(handle)
    assert isinstance(recorded, dict)
    return cast("dict[str, Any]", recorded)


def _config(stale_after: timedelta = timedelta(hours=24)) -> Config:
    return Config(
        credential_name="BILLING_CONNECTOR_TOKEN",
        queue_url="https://queue.test/billing-connector",
        ledger_base_url="https://ledger.test",
        stale_after=stale_after,
    )


def _event(
    *,
    event_id: str = "event-2",
    subject_type: str = "billing_episode",
    subject_key: str = "episode-1001",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "subject_type": subject_type,
        "subject_key": subject_key,
        "effective_at": "2026-08-31T00:00:00+00:00",
        "payload": payload or {"achieved": True},
    }


class _FakeStore:
    """`billing.store.PostgresFactStore`'s three surfaces the service touches, with no Postgres
    behind them: the fold (`apply_event`), the evaluate-time read (`load_snapshot`), and the
    `evaluations` append (`record_evaluation`). Every call is recorded so a test can assert what
    the service did *and* what it did not do — "evaluates nothing" is an empty `loaded` list."""

    def __init__(self, snapshot: SubjectFactsSnapshot | None = None, *, applied: bool = True) -> None:
        self._snapshot = snapshot
        self._applied = applied
        self.folded: list[dict[str, object]] = []
        self.loaded: list[tuple[str, str]] = []
        self.recorded: list[dict[str, object]] = []

    def apply_event(self, envelope: Any) -> bool:
        self.folded.append(dict(cast("dict[str, object]", envelope)))
        return self._applied

    def load_snapshot(self, subject_type: str, subject_key: str) -> SubjectFactsSnapshot | None:
        self.loaded.append((subject_type, subject_key))
        return self._snapshot

    def record_evaluation(
        self,
        *,
        subject_type: str,
        subject_key: str,
        verdict_type: str,
        rule_version: str,
        outcome: str,
        as_of: datetime,
        declared_event_id: str,
    ) -> bool:
        self.recorded.append({
            "subject_type": subject_type,
            "subject_key": subject_key,
            "verdict_type": verdict_type,
            "rule_version": rule_version,
            "outcome": outcome,
            "as_of": as_of,
            "declared_event_id": declared_event_id,
        })
        return True


class _FakeSqs:
    """One scripted `receive_message` answer per pass, then empty; every delete recorded.

    Each pass's messages are wrapped the way an EventBridge rule delivers them (`detail` holding
    the envelope), which is the shape `pulse_core.connector.consume_once` unwraps.
    """

    def __init__(self, passes: list[list[dict[str, object]]]) -> None:
        self._passes = list(passes)
        self.deleted: list[str] = []
        self.receives = 0

    def receive_message(self, **_kwargs: object) -> dict[str, object]:
        self.receives += 1
        if not self._passes:
            return {}
        envelopes = self._passes.pop(0)
        return {
            "Messages": [
                {"Body": json.dumps({"detail": envelope}), "ReceiptHandle": f"rh-{index}"}
                for index, envelope in enumerate(envelopes)
            ]
        }

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        assert QueueUrl == "https://queue.test/billing-connector"
        self.deleted.append(ReceiptHandle)


def committed(event_id: str = _DECLARED_EVENT_ID) -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = _DECLARED_EVENT_ID) -> httpx.Response:
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


def _fresh_episode_facts(**overrides: object) -> SubjectFactsSnapshot:
    """The `fact_arrives_verdict_follows` recording's own facts, fresh: an achieved period whose
    consent starts before it closes, which the shipped rule resolves `positive`."""
    facts: dict[str, object] = {"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"}
    facts.update(overrides)
    return make_facts(subject_type="billing_episode", subject_key="episode-1001", facts=facts)


class TestSignatures:
    def test_run_batch_signature_matches_the_work_order(self) -> None:
        parameters = list(inspect.signature(run_batch).parameters)
        assert parameters == ["store", "config", "client", "envelope", "registry"]

    def test_run_batch_registry_is_keyword_only_and_optional(self) -> None:
        registry = inspect.signature(run_batch).parameters["registry"]
        assert registry.kind is inspect.Parameter.KEYWORD_ONLY
        assert registry.default is None

    def test_run_batch_return_annotation_is_receipt(self) -> None:
        assert inspect.signature(run_batch).return_annotation == "Receipt"

    def test_main_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(main).parameters) == ["argv"]

    def test_main_return_annotation_is_int(self) -> None:
        assert inspect.signature(main).return_annotation == "int"

    def test_run_exposes_every_transport_as_a_seam(self) -> None:
        parameters = list(inspect.signature(run).parameters)
        assert parameters == [
            "config",
            "store",
            "client",
            "registry",
            "sqs_client",
            "deduper",
            "iterations",
            "sleep",
        ]


class TestTheTriggerSetIsAClosedAllowlist:
    """Design.md decision 4 as amended 2026-09-02: episode and coverage subject events trigger;
    everything else folds and defers."""

    def test_the_allowlist_is_exactly_episode_and_coverage(self) -> None:
        assert frozenset({"billing_episode", "coverage"}) == TRIGGER_SUBJECT_TYPES

    @pytest.mark.parametrize("subject_type", ["consent", "enrollment", "patient", "care_plan"])
    def test_no_other_subject_type_triggers_evaluation(self, subject_type: str) -> None:
        assert subject_type not in TRIGGER_SUBJECT_TYPES

    def test_the_writer_identity_is_this_connectors_own(self) -> None:
        assert WRITER_ID == "billing-connector"


class TestAFactArrivesAVerdictFollows:
    """Spec: "A fact arrives, a verdict follows" — the `fact_arrives_verdict_follows` recording,
    replayed through the real path."""

    def test_an_episode_event_evaluates_and_declares_its_verdict(self) -> None:
        recording = _load_fixture("fact_arrives_verdict_follows")
        store = _FakeStore(_fresh_episode_facts())
        transport = FakeCommandTransport()

        receipt = run_batch(
            cast("Any", store),
            _config(),
            transport.client(),
            cast("dict[str, object]", recording["event"]),
            registry=_REGISTRY,
        )

        expected = recording["expected"]
        assert receipt.evaluated == expected["evaluated"]
        assert receipt.committed == expected["committed"]
        assert receipt.replayed == expected["replayed"]
        assert receipt.rejected == expected["rejected"]
        assert receipt.deferred == expected["deferred"]

    def test_it_evaluates_exactly_the_affected_subject(self) -> None:
        store = _FakeStore(_fresh_episode_facts())

        run_batch(
            cast("Any", store),
            _config(),
            FakeCommandTransport().client(),
            _event(subject_key="episode-1001"),
            registry=_REGISTRY,
        )

        assert store.loaded == [("billing_episode", "episode-1001")]

    def test_the_event_is_folded_before_it_is_evaluated(self) -> None:
        store = _FakeStore(_fresh_episode_facts())
        envelope = _event()

        run_batch(cast("Any", store), _config(), FakeCommandTransport().client(), envelope, registry=_REGISTRY)

        assert store.folded == [envelope]

    def test_the_verdict_is_followed_by_its_paired_transition(self) -> None:
        transport = FakeCommandTransport()

        run_batch(
            cast("Any", _FakeStore(_fresh_episode_facts())),
            _config(),
            transport.client(),
            _event(),
            registry=_REGISTRY,
        )

        commands = [body["event_type"] for body in transport.bodies]
        assert commands == ["declare_verdict", "declare_transition"]

    def test_a_coverage_event_evaluates_but_the_registry_lists_no_coverage_verdict_type(self) -> None:
        """A coverage subject triggers evaluation in full; today's registry has no module whose
        `SUBJECT_TYPE` is `coverage`, so it produces nothing — an evaluated-nothing pass, not a
        deferral: nothing about it waits on a catalog fact."""
        store = _FakeStore(make_facts(subject_type="coverage", subject_key="coverage-77"))
        transport = FakeCommandTransport()

        receipt = run_batch(
            cast("Any", store),
            _config(),
            transport.client(),
            _event(subject_type="coverage", subject_key="coverage-77", payload={"covered": True}),
            registry=_REGISTRY,
        )

        assert store.loaded == [("coverage", "coverage-77")]
        assert receipt == Receipt()
        assert transport.bodies == []


class TestConsentAndEnrollmentFanOutWaitForTheirFact:
    """Spec: "Consent and enrollment fan-out wait for their fact" — folded, evaluated against
    nothing, counted `deferred` (design.md decision 4)."""

    def test_the_recorded_consent_scenario_defers(self) -> None:
        recording = _load_fixture("consent_enrollment_fanout_deferred")
        store = _FakeStore()
        transport = FakeCommandTransport()

        receipt = run_batch(
            cast("Any", store),
            _config(),
            transport.client(),
            cast("dict[str, object]", recording["event"]),
            registry=_REGISTRY,
        )

        expected = recording["expected"]
        assert receipt.deferred == expected["deferred"]
        assert receipt.evaluated == expected["evaluated"]
        assert receipt.committed == expected["committed"]

    @pytest.mark.parametrize("subject_type", ["consent", "enrollment"])
    def test_consent_and_enrollment_events_fold_and_defer(self, subject_type: str) -> None:
        store = _FakeStore()
        transport = FakeCommandTransport()

        receipt = run_batch(
            cast("Any", store),
            _config(),
            transport.client(),
            _event(subject_type=subject_type, subject_key=f"{subject_type}-501", payload={"granted": True}),
            registry=_REGISTRY,
        )

        assert receipt == Receipt(deferred=1)
        assert len(store.folded) == 1
        assert store.loaded == []
        assert transport.bodies == []
        assert store.recorded == []


class TestARedeliveredEventEvaluatesOnce:
    def test_a_fold_that_finds_nothing_new_evaluates_nothing(self) -> None:
        """`apply_event` is `False` for an event id the subject already recorded, or a fact older
        than what is folded — the guard that holds across a restart, where the kit's in-process
        dedupe has no memory of the first delivery."""
        store = _FakeStore(_fresh_episode_facts(), applied=False)
        transport = FakeCommandTransport()

        receipt = run_batch(
            cast("Any", store),
            _config(),
            transport.client(),
            _event(),
            registry=_REGISTRY,
        )

        assert receipt == Receipt()
        assert store.loaded == []
        assert transport.bodies == []

    def test_a_redelivery_within_one_run_reaches_the_handler_once(self) -> None:
        """The kit's own `event_id` dedupe: the second copy is deleted without the handler
        running again, so the subject is evaluated once and the message still leaves the queue."""
        store = _FakeStore(_fresh_episode_facts())
        envelope = _event(event_id="event-redelivered")
        sqs = _FakeSqs([[envelope, envelope]])

        receipt = run(
            _config(),
            store=cast("Any", store),
            client=FakeCommandTransport().client(),
            registry=_REGISTRY,
            sqs_client=sqs,
            iterations=1,
        )

        assert len(store.folded) == 1
        assert receipt.evaluated == 1
        assert len(sqs.deleted) == 2


class TestEveryEvaluationIsRecordedWithItsDeclaredEventId:
    """Spec: "Each evaluation SHALL be recorded in the engine's `evaluations` store with the
    declared event id"."""

    def test_a_committed_verdict_records_its_evaluation(self) -> None:
        store = _FakeStore(_fresh_episode_facts())
        transport = FakeCommandTransport([committed()])

        run_batch(cast("Any", store), _config(), transport.client(), _event(), registry=_REGISTRY)

        assert len(store.recorded) == 1
        recorded = store.recorded[0]
        assert recorded["subject_type"] == "billing_episode"
        assert recorded["subject_key"] == "episode-1001"
        assert recorded["verdict_type"] == "billing_eligibility"
        assert recorded["rule_version"] == billing_eligibility.RULE_VERSION
        assert recorded["outcome"] == "positive"
        assert recorded["declared_event_id"] == _DECLARED_EVENT_ID

    def test_a_replayed_verdict_records_the_event_id_the_original_commit_produced(self) -> None:
        store = _FakeStore(_fresh_episode_facts())
        transport = FakeCommandTransport([replayed()])

        receipt = run_batch(cast("Any", store), _config(), transport.client(), _event(), registry=_REGISTRY)

        assert receipt == Receipt(evaluated=1, replayed=1)
        assert [row["declared_event_id"] for row in store.recorded] == [_DECLARED_EVENT_ID]

    def test_a_rejected_verdict_records_nothing(self) -> None:
        """No declared event id exists — nothing took effect, and the column is the table's own
        unique key — so there is no row to write; the rejection lives in the receipt."""
        store = _FakeStore(_fresh_episode_facts())
        transport = FakeCommandTransport([rejected("unknown subject type")])

        receipt = run_batch(cast("Any", store), _config(), transport.client(), _event(), registry=_REGISTRY)

        assert receipt == Receipt(evaluated=1, rejected=1)
        assert store.recorded == []

    def test_the_recorded_row_carries_no_facts_and_no_amounts(self) -> None:
        """Spec: "No monetary value crosses the seam" — the row is a lineage record, so an
        amount-bearing fact in the snapshot reaches neither its keys nor its values."""
        store = _FakeStore(_fresh_episode_facts(billed_amount_cents=12345))
        transport = FakeCommandTransport()

        run_batch(cast("Any", store), _config(), transport.client(), _event(), registry=_REGISTRY)

        rendered = json.dumps(store.recorded, default=str)
        assert "billed_amount_cents" not in rendered
        assert "12345" not in rendered


class TestARejectedTransitionKeepsItsEvidence:
    def test_the_verdict_commits_and_the_transition_counts_rejected(self) -> None:
        store = _FakeStore(_fresh_episode_facts())
        transport = FakeCommandTransport([committed(), rejected()])

        receipt = run_batch(cast("Any", store), _config(), transport.client(), _event(), registry=_REGISTRY)

        assert receipt == Receipt(evaluated=1, committed=1, rejected=1)
        assert len(store.recorded) == 1


class TestAStaleWatermarkDeclaresEvidenceOnly:
    def test_an_indeterminate_verdict_declares_no_transition_and_is_still_recorded(self) -> None:
        """Spec: "A stale watermark yields awaiting_source" — evidence declares, no transition
        follows, and the evaluation is recorded like any other."""
        store = _FakeStore(
            make_stale_facts(
                subject_type="billing_episode",
                subject_key="episode-1003",
                facts={"period_end": "2026-08-31", "achieved": True, "consent_start": "2026-07-01"},
            )
        )
        transport = FakeCommandTransport()

        receipt = run_batch(
            cast("Any", store),
            _config(),
            transport.client(),
            _event(subject_key="episode-1003"),
            registry=_REGISTRY,
        )

        assert receipt == Receipt(evaluated=1, committed=1)
        assert [body["event_type"] for body in transport.bodies] == ["declare_verdict"]
        assert store.recorded[0]["outcome"] == "indeterminate"


class TestEveryRunEndsInACountedReceipt:
    """Spec: "Every run ends in a counted receipt", "The receipt shape is stable"."""

    def test_one_pass_logs_exactly_one_receipt_line(self, caplog: pytest.LogCaptureFixture) -> None:
        store = _FakeStore(_fresh_episode_facts())
        sqs = _FakeSqs([[_event(event_id="event-a")]])

        with caplog.at_level(logging.INFO, logger="billing_connector.service"):
            receipt = run(
                _config(),
                store=cast("Any", store),
                client=FakeCommandTransport().client(),
                registry=_REGISTRY,
                sqs_client=sqs,
                iterations=1,
            )

        receipt_lines = [message for message in caplog.messages if message.startswith("service=billing-connector")]
        assert receipt_lines == [
            "service=billing-connector committed=1 replayed=0 rejected=0 evaluated=1 deferred=0",
            "service=billing-connector committed=1 replayed=0 rejected=0 evaluated=1 deferred=0",
        ]
        assert receipt.format_line() == receipt_lines[-1]

    def test_the_run_total_sums_every_pass(self) -> None:
        store = _FakeStore(_fresh_episode_facts())
        sqs = _FakeSqs([
            [_event(event_id="event-a"), _event(event_id="event-b", subject_type="consent")],
            [_event(event_id="event-c")],
        ])

        receipt = run(
            _config(),
            store=cast("Any", store),
            client=FakeCommandTransport().client(),
            registry=_REGISTRY,
            sqs_client=sqs,
            iterations=2,
        )

        assert receipt == Receipt(committed=2, evaluated=2, deferred=1)

    def test_the_golden_line_matches_the_recorded_shape(self) -> None:
        recording = _load_fixture("receipt_shape_is_stable")
        counts = recording["receipt"]

        line = Receipt(
            committed=counts["committed"],
            replayed=counts["replayed"],
            rejected=counts["rejected"],
            evaluated=counts["evaluated"],
            deferred=counts["deferred"],
        ).format_line()

        assert line == recording["expected"]["line"]

    def test_no_receipt_line_carries_anything_but_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        """Spec: "the receipt SHALL carry counts and subject keys only" — the line itself is
        counts alone, so an amount-bearing fact cannot reach it."""
        store = _FakeStore(_fresh_episode_facts(billed_amount_cents=12345))
        sqs = _FakeSqs([[_event()]])

        with caplog.at_level(logging.INFO, logger="billing_connector.service"):
            run(
                _config(),
                store=cast("Any", store),
                client=FakeCommandTransport().client(),
                registry=_REGISTRY,
                sqs_client=sqs,
                iterations=1,
            )

        for message in caplog.messages:
            assert "billed_amount_cents" not in message
            assert "12345" not in message


class TestAFailingPassBacksOffAndKeepsGoing:
    def test_a_raising_pass_is_backed_off_and_the_next_pass_still_counts(self) -> None:
        class _RaisingOnceSqs(_FakeSqs):
            def receive_message(self, **kwargs: object) -> dict[str, object]:
                if self.receives == 0:
                    self.receives += 1
                    msg = "the queue is unreachable"
                    raise RuntimeError(msg)
                return super().receive_message(**kwargs)

        slept: list[float] = []
        sqs = _RaisingOnceSqs([[_event()]])

        receipt = run(
            _config(),
            store=cast("Any", _FakeStore(_fresh_episode_facts())),
            client=FakeCommandTransport().client(),
            registry=_REGISTRY,
            sqs_client=sqs,
            iterations=2,
            sleep=slept.append,
        )

        assert slept == [5.0]
        assert receipt == Receipt(committed=1, evaluated=1)


class TestStartupRefusals:
    """Spec: "A missing value names itself", "A registry mismatch halts startup" — both before
    any connection is opened, so neither test needs a transport."""

    def test_a_missing_variable_names_itself_and_nothing_else(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BILLING_CONNECTOR_TOKEN", raising=False)
        monkeypatch.delenv("BILLING_CONNECTOR_QUEUE_URL", raising=False)
        monkeypatch.delenv("BILLING_CONNECTOR_LEDGER_BASE_URL", raising=False)

        with pytest.raises(MissingConfigVariableError) as raised:
            main([])

        assert raised.value.name == "BILLING_CONNECTOR_TOKEN"
        assert "BILLING_CONNECTOR_TOKEN" in str(raised.value)

    def test_a_registry_mismatch_halts_before_consuming(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BILLING_CONNECTOR_TOKEN", "unit-test-token")
        monkeypatch.setenv("BILLING_CONNECTOR_QUEUE_URL", "https://queue.test/billing-connector")
        monkeypatch.setenv("BILLING_CONNECTOR_LEDGER_BASE_URL", "https://ledger.test")
        monkeypatch.setattr(
            "billing_connector.service.resolve_registry",
            lambda: {"coverage_eligibility": billing_eligibility},
        )

        with pytest.raises(RegistryMismatchError) as raised:
            main([])

        assert "coverage_eligibility" in str(raised.value)


class TestResolveRegistry:
    def test_it_returns_the_engines_registered_verdict_types(self) -> None:
        from billing.rules.registry import VERDICT_TYPES

        assert resolve_registry() == dict(VERDICT_TYPES)

    def test_it_is_a_copy_no_caller_can_mutate_the_registry_through(self) -> None:
        from billing.rules.registry import VERDICT_TYPES

        resolved = resolve_registry()
        resolved.pop("billing_eligibility")

        assert "billing_eligibility" in VERDICT_TYPES
