"""`verdict_relay.declarer` — mart row → attributed, idempotent `declare_verdict` command.

Covers task 2.2's scenarios (verdict-declare): a replay is an idempotent hit and never
re-declares; a rejection is counted, logged with the ledger's reason, and never retried; a
transient failure retries with backoff then fails the run naming the row. Plus the pre-submission
validation and stale-skip behaviour the same module owns.

The command API is faked at the client boundary (`httpx.MockTransport` under a real
`PulseCoreClient`), per the change's testing posture; `conftest.py` blocks sockets for every run.
"""

from __future__ import annotations

import json
import logging
from typing import cast

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from verdict_relay.declarer import (
    DECLARE_MAX_ATTEMPTS,
    Declarer,
    MissingCredentialError,
    RowDisposition,
    RowValidationError,
    TransientExhaustedError,
    service_client,
)

SUBJECT_TYPE_BY_VERDICT = {"billing_qualification": "billing_episode"}


def mart_row(**overrides: object) -> dict[str, object]:
    """One synthetic mart-contract row; keyword overrides mutate nothing shared."""
    row: dict[str, object] = {
        "subject_id": "episode-0001",
        "verdict_type": "billing_qualification",
        "outcome": "positive",
        "reason": None,
        "rule_version": "rules-v3",
        "as_of": "2026-08-01T00:00:00+00:00",
        "lineage_ref": "dbt-run-2026-08-01T02",
        "computed_at": "2026-08-01T02:00:00+00:00",
    }
    row.update(overrides)
    return row


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": True})


def rejected(reason: str = "illegal transition") -> httpx.Response:
    return httpx.Response(
        422,
        json={
            "detail": {
                "message": "verdict regresses the subject's state",
                "reason": reason,
                "catalog_version": "appendix-c-v0.7",
            }
        },
    )


def transient() -> httpx.Response:
    return httpx.Response(503, text="upstream unavailable")


class ScriptedApi:
    """The command API faked at the client boundary: scripted answers, recorded request bodies.

    The last scripted response repeats for any further request, so "transient forever" is one
    entry.
    """

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        # max_attempts=1: retry policy belongs to the declarer (design decision 4), so the
        # client must surface a transient classification rather than retrying it itself.
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


def declarer_over(
    api: ScriptedApi,
    *,
    watermarks: dict[str, str] | None = None,
    sleeps: list[float] | None = None,
) -> Declarer:
    recorded = sleeps if sleeps is not None else []
    return Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        watermarks=watermarks,
        sleep=recorded.append,
        jitter=lambda: 1.0,
    )


class TestReplayScenario:
    """Scenario: a replay is an idempotent hit, not a second declaration."""

    def test_replay_counts_and_never_redeclares(self) -> None:
        api = ScriptedApi([replayed()])
        declarer = declarer_over(api)

        disposition = declarer.declare(mart_row())

        assert disposition is RowDisposition.REPLAYED
        assert declarer.counts.replayed == 1
        assert declarer.counts.declared == 0
        assert len(api.bodies) == 1  # no retry, no second declaration

    def test_replay_advances_the_watermark_like_a_commit(self) -> None:
        api = ScriptedApi([replayed()])
        declarer = declarer_over(api)
        declarer.declare(mart_row(as_of="2026-08-01T00:00:00+00:00"))
        assert declarer.watermarks["episode-0001"] == "2026-08-01T00:00:00+00:00"


class TestRejectionScenario:
    """Scenario: a rejection is counted, logged with the ledger's reason, and never retried."""

    def test_rejection_counts_logs_the_reason_and_never_retries(self, caplog: pytest.LogCaptureFixture) -> None:
        api = ScriptedApi([rejected(reason="illegal transition")])
        declarer = declarer_over(api)

        with caplog.at_level(logging.WARNING, logger="verdict_relay.declarer"):
            disposition = declarer.declare(mart_row())

        assert disposition is RowDisposition.REJECTED
        assert declarer.counts.rejected == 1
        assert len(api.bodies) == 1  # never retried
        rejection_logs = [r for r in caplog.records if "rejected" in r.getMessage()]
        assert len(rejection_logs) == 1
        message = rejection_logs[0].getMessage()
        assert "illegal transition" in message  # the ledger's reason
        assert "appendix-c-v0.7" in message  # and its catalog version
        assert "episode-0001" in message  # subject key only, never demographics

    def test_rejection_does_not_advance_the_watermark(self) -> None:
        api = ScriptedApi([rejected()])
        declarer = declarer_over(api)
        declarer.declare(mart_row())
        assert "episode-0001" not in declarer.watermarks


class TestTransientScenario:
    """Scenario: a transient failure retries with backoff then fails the run naming the row."""

    def test_transient_exhausts_five_attempts_and_names_the_row(self) -> None:
        api = ScriptedApi([transient()])
        sleeps: list[float] = []
        declarer = declarer_over(api, sleeps=sleeps)

        with pytest.raises(TransientExhaustedError) as excinfo:
            declarer.declare(mart_row())

        assert len(api.bodies) == DECLARE_MAX_ATTEMPTS == 5  # exactly 5 attempts
        message = str(excinfo.value)
        assert "episode-0001" in message  # the failure identifies the failing row
        assert "billing_qualification" in message
        assert "5" in message

    def test_backoff_is_exponential_and_jitter_scaled(self) -> None:
        api = ScriptedApi([transient()])
        sleeps: list[float] = []
        declarer = declarer_over(api, sleeps=sleeps)

        with pytest.raises(TransientExhaustedError):
            declarer.declare(mart_row())

        # 4 backoffs between 5 attempts; jitter=1.0 pins each at its full exponential value.
        assert sleeps == [0.5, 1.0, 2.0, 4.0]

    def test_transient_then_commit_recovers_within_the_attempt_budget(self) -> None:
        api = ScriptedApi([transient(), transient(), committed()])
        declarer = declarer_over(api)

        disposition = declarer.declare(mart_row())

        assert disposition is RowDisposition.DECLARED
        assert declarer.counts.declared == 1
        assert len(api.bodies) == 3


class TestCommandMapping:
    def test_commit_submits_the_attributed_idempotent_command(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)

        disposition = declarer.declare(mart_row())

        assert disposition is RowDisposition.DECLARED
        (body,) = api.bodies
        assert body["subject_type"] == "billing_episode"
        assert body["subject_key"] == "episode-0001"
        assert body["event_type"] == "declare_verdict"
        assert body["effective_at"] == "2026-08-01T00:00:00+00:00"
        payload = body["payload"]
        assert isinstance(payload, dict)
        assert payload["rule_version"] == "rules-v3"
        assert payload["as_of"] == "2026-08-01T00:00:00Z"
        assert payload["lineage"] == {
            "lineage_ref": "dbt-run-2026-08-01T02",
            "verdict_type": "billing_qualification",
        }
        # The D16 key is derived client-side: writer id, then the fact digest.
        key = body["idempotency_key"]
        assert isinstance(key, str)
        assert key.startswith("verdict-relay:")
        # Attribution is the credential's, applied server-side — a body carrying actor fields
        # would be a spoof attempt (D15).
        assert not any(field.startswith("actor") for field in body)

    def test_the_same_row_derives_the_same_idempotency_key(self) -> None:
        first = ScriptedApi([committed()])
        second = ScriptedApi([committed()])
        declarer_over(first).declare(mart_row())
        declarer_over(second).declare(mart_row())
        assert first.bodies[0]["idempotency_key"] == second.bodies[0]["idempotency_key"]


class TestStaleSkip:
    def test_a_row_older_than_the_watermark_is_skipped_not_declared(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api, watermarks={"episode-0001": "2026-08-02T00:00:00+00:00"})

        disposition = declarer.declare(mart_row(as_of="2026-08-01T00:00:00+00:00"))

        assert disposition is RowDisposition.SKIPPED_STALE
        assert declarer.counts.skipped_stale == 1
        assert api.bodies == []  # never declared, never an error

    def test_a_row_equal_to_the_watermark_is_declared_for_idempotency_to_answer(self) -> None:
        api = ScriptedApi([replayed()])
        declarer = declarer_over(api, watermarks={"episode-0001": "2026-08-01T00:00:00+00:00"})
        disposition = declarer.declare(mart_row(as_of="2026-08-01T00:00:00+00:00"))
        assert disposition is RowDisposition.REPLAYED
        assert len(api.bodies) == 1

    def test_the_watermark_compares_instants_not_strings(self) -> None:
        api = ScriptedApi([committed()])
        # 01:00+02:00 is 23:00Z the day before — older than the watermark despite the larger
        # local-time string.
        declarer = declarer_over(api, watermarks={"episode-0001": "2026-08-01T00:00:00+00:00"})
        disposition = declarer.declare(mart_row(as_of="2026-08-01T01:00:00+02:00"))
        assert disposition is RowDisposition.SKIPPED_STALE
        assert api.bodies == []

    def test_a_commit_advances_the_watermark_to_the_declared_instant(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)
        declarer.declare(mart_row(as_of="2026-08-03T05:00:00+00:00"))
        assert declarer.watermarks == {"episode-0001": "2026-08-03T05:00:00+00:00"}


class TestPreSubmissionValidation:
    def test_indeterminate_without_a_reason_fails_before_any_api_call(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)

        with pytest.raises(RowValidationError) as excinfo:
            declarer.declare(mart_row(outcome="indeterminate", reason=None))

        assert api.bodies == []  # no API call occurs
        assert "episode-0001" in str(excinfo.value)
        assert "reason" in str(excinfo.value)

    def test_indeterminate_with_a_reason_declares_normally(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)
        disposition = declarer.declare(mart_row(outcome="indeterminate", reason="insufficient device days"))
        assert disposition is RowDisposition.DECLARED
        payload = api.bodies[0]["payload"]
        assert isinstance(payload, dict)
        assert payload["reason"] == "insufficient device days"

    def test_an_outcome_outside_the_trinary_enum_fails_validation(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)
        with pytest.raises(RowValidationError):
            declarer.declare(mart_row(outcome="maybe"))
        assert api.bodies == []

    def test_a_missing_contract_column_fails_naming_the_row(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)
        row = mart_row()
        del row["rule_version"]
        with pytest.raises(RowValidationError) as excinfo:
            declarer.declare(row)
        assert "rule_version" in str(excinfo.value)
        assert api.bodies == []

    def test_an_unmapped_verdict_type_fails_naming_the_row(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)
        with pytest.raises(RowValidationError) as excinfo:
            declarer.declare(mart_row(verdict_type="unheard-of"))
        assert "unheard-of" in str(excinfo.value)
        assert api.bodies == []

    def test_a_naive_as_of_fails_before_any_api_call(self) -> None:
        api = ScriptedApi([committed()])
        declarer = declarer_over(api)
        with pytest.raises(RowValidationError) as excinfo:
            declarer.declare(mart_row(as_of="2026-08-01T00:00:00"))
        assert "timezone" in str(excinfo.value)
        assert api.bodies == []


class TestServiceClient:
    """D15: the credential *name* is configuration; the value comes from the environment."""

    def test_the_token_is_read_from_the_named_environment_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VERDICT_RELAY_TOKEN", "from-environment")
        api = ScriptedApi([committed()])
        client = service_client(
            "http://ledger.test",
            writer_id="verdict-relay",
            token_env="VERDICT_RELAY_TOKEN",  # noqa: S106 — a variable name, not a secret
            transport=httpx.MockTransport(api.handler),
        )
        declarer = Declarer(client, subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT, sleep=lambda _s: None)
        assert declarer.declare(mart_row()) is RowDisposition.DECLARED

    def test_a_missing_credential_fails_naming_the_variable_not_a_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VERDICT_RELAY_TOKEN", raising=False)
        with pytest.raises(MissingCredentialError) as excinfo:
            service_client(
                "http://ledger.test",
                writer_id="verdict-relay",
                token_env="VERDICT_RELAY_TOKEN",  # noqa: S106 — a variable name, not a secret
            )
        assert "VERDICT_RELAY_TOKEN" in str(excinfo.value)
