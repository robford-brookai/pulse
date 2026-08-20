"""Fixture corpus — recorded synthetic mart rows driving the relay end to end (task 4.1).

`tests/fixtures/` holds one JSON recording per work-order case: normal declare, idempotent replay,
out-of-order stale run, illegal-transition rejection, indeterminate-with-reason, and
indeterminate-without-reason — plus one recording per shipped verdict type (billing-state task
2.2): `billing_eligibility`, `coverage_eligibility`, and `benefits_verification` rows whose
shipped `transition_by_outcome` entries pair a `declare_transition` with the verdict (two API
calls per row). Each recording carries the mart rows, the pre-existing watermarks,
the scripted API classifications, and the expected receipt counts — so the suite here replays every
case through the real reader → declarer → run path over the faked client.

Covers the verdict-declare scenarios "A normal declare commits with attribution and lineage",
"Indeterminate with a reason declares normally", and "Indeterminate without a reason fails before
the API call" (zero API calls, asserted on the fake). The command API is faked at the client
boundary (`httpx.MockTransport`); `conftest.py` blocks sockets for every run.

Fixtures are synthetic by construction (design risk: PHI) — a corpus test pins every row to exactly
the contract columns, so a demographic field can never ride along in a recording.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from verdict_relay import config
from verdict_relay.declarer import Declarer
from verdict_relay.mart_reader import CONTRACT_COLUMNS, FixtureRowSource, MartReader
from verdict_relay.run import RunReceipt, run_relay

FIXTURES_DIR = Path(__file__).parent / "fixtures"

#: The six S1 work-order cases plus the three shipped-verdict-type cases (billing-state task
#: 2.2); one recording each, `<case>.json`.
CASES = (
    "normal_declare",
    "idempotent_replay",
    "out_of_order_stale_run",
    "illegal_transition_rejection",
    "indeterminate_with_reason",
    "indeterminate_without_reason",
    "billing_eligibility_qualifies",
    "coverage_eligibility_verifies",
    "benefits_verification_verifies",
)

#: The shipped configuration plus the S1 recordings' synthetic type, which deliberately has no
#: `transition_by_outcome` entry — those recordings double as the pin that an unconfigured type
#: still submits exactly one command under the shipped pairing config.
SUBJECT_TYPE_BY_VERDICT = {
    **config.SUBJECT_TYPE_BY_VERDICT,
    "billing_qualification": "billing_episode",
}

#: Scripted responses by the classification name a recording uses.
RESPONSES = {
    "committed": lambda: httpx.Response(201, json={"event_id": "e1", "replayed": False}),
    "replayed": lambda: httpx.Response(201, json={"event_id": "e1", "replayed": True}),
    "rejected": lambda: httpx.Response(
        422,
        json={
            "detail": {
                "message": "verdict regresses the subject's state",
                "reason": "illegal transition",
                "catalog_version": "appendix-c-v0.7",
            }
        },
    ),
}


class ScriptedApi:
    """The command API faked at the client boundary; the last scripted response repeats.

    A recording that expects zero API calls scripts an empty response list, so any submission
    fails loudly instead of silently succeeding.
    """

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        assert self._responses, "this recording scripts no API responses; no call should occur"
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


class MemoryCursorStore:
    """An in-memory `CursorStore`, cursor persistence being out of scope for these recordings."""

    def __init__(self) -> None:
        self._cursor: dict[str, object] | None = None

    def load(self) -> dict[str, object] | None:
        return self._cursor

    def save(self, cursor: object) -> None:
        assert isinstance(cursor, dict)
        self._cursor = cast("dict[str, object]", cursor)


def load_case(name: str) -> dict[str, object]:
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as handle:
        recorded: object = json.load(handle)
    assert isinstance(recorded, dict)
    return cast("dict[str, object]", recorded)


def rows_of(recording: dict[str, object]) -> list[dict[str, object]]:
    rows = recording["rows"]
    assert isinstance(rows, list)
    return cast("list[dict[str, object]]", rows)


def expected_of(recording: dict[str, object]) -> dict[str, int]:
    expected = recording["expected"]
    assert isinstance(expected, dict)
    return cast("dict[str, int]", expected)


def replay_recording(recording: dict[str, object]) -> tuple[RunReceipt, ScriptedApi]:
    """Drive one recording through the real read → declare → receipt path over the fake."""
    scripted = cast("list[str]", recording.get("responses", []))
    api = ScriptedApi([RESPONSES[name]() for name in scripted])
    watermarks = cast("dict[str, str]", recording.get("watermarks") or {})
    declarer = Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        transition_by_outcome=config.TRANSITION_BY_OUTCOME,
        watermarks=watermarks,
        sleep=lambda _s: None,
        jitter=lambda: 0.0,
    )
    reader = MartReader(FixtureRowSource(rows_of(recording)), MemoryCursorStore())
    return run_relay(reader, declarer), api


class TestCorpusCoverage:
    """The corpus is complete, on-contract, and synthetic by construction."""

    def test_the_corpus_records_exactly_the_registered_cases(self) -> None:
        recorded = sorted(path.stem for path in FIXTURES_DIR.glob("*.json"))
        assert recorded == sorted(CASES)

    @pytest.mark.parametrize("name", CASES)
    def test_every_row_carries_exactly_the_contract_columns(self, name: str) -> None:
        # Exactly the mart contract — a demographic field could never ride along in a recording.
        for row in rows_of(load_case(name)):
            assert set(row) == set(CONTRACT_COLUMNS)

    @pytest.mark.parametrize("name", CASES)
    def test_every_recording_names_its_case_and_expectation(self, name: str) -> None:
        recording = load_case(name)
        assert recording["case"] == name
        assert set(expected_of(recording)) == {
            "declared",
            "replayed",
            "skipped_stale",
            "rejected",
            "failed",
            "api_calls",
        }


class TestRecordedCasesEndToEnd:
    """Each recording replays to exactly the receipt it recorded."""

    @pytest.mark.parametrize("name", CASES)
    def test_the_receipt_matches_the_recording(self, name: str) -> None:
        recording = load_case(name)
        receipt, api = replay_recording(recording)

        expected = expected_of(recording)
        assert receipt.declared == expected["declared"]
        assert receipt.replayed == expected["replayed"]
        assert receipt.skipped_stale == expected["skipped_stale"]
        assert receipt.rejected == expected["rejected"]
        assert receipt.failed == expected["failed"]
        assert len(api.bodies) == expected["api_calls"]
        assert receipt.succeeded == (expected["failed"] == 0)


class TestNormalDeclareScenario:
    """Scenario: a normal declare commits with attribution and lineage."""

    def test_the_command_carries_attribution_lineage_and_the_d16_key(self) -> None:
        recording = load_case("normal_declare")
        (row,) = rows_of(recording)

        receipt, api = replay_recording(recording)

        assert receipt.declared == 1  # the response classifies as committed
        (body,) = api.bodies
        # Attribution is the service credential's, applied server-side (D15) — the body names
        # the subject, never an actor.
        assert body["subject_type"] == "billing_episode"
        assert body["subject_key"] == row["subject_id"]
        assert body["event_type"] == "declare_verdict"
        assert not any(field.startswith("actor") for field in body)
        payload = body["payload"]
        assert isinstance(payload, dict)
        assert payload["rule_version"] == row["rule_version"]
        assert payload["lineage"] == {
            "lineage_ref": row["lineage_ref"],
            "verdict_type": row["verdict_type"],
        }
        # The D16 idempotency key is derived client-side under the relay's writer id.
        key = body["idempotency_key"]
        assert isinstance(key, str)
        assert key.startswith("verdict-relay:")


class TestIndeterminateScenarios:
    """Scenarios: indeterminate with a reason declares normally; without one, no API call."""

    def test_indeterminate_with_a_reason_commits_carrying_the_reason(self) -> None:
        recording = load_case("indeterminate_with_reason")
        (row,) = rows_of(recording)

        receipt, api = replay_recording(recording)

        assert receipt.declared == 1
        (body,) = api.bodies
        payload = body["payload"]
        assert isinstance(payload, dict)
        assert payload["reason"] == row["reason"]

    def test_indeterminate_without_a_reason_fails_validation_with_zero_api_calls(self) -> None:
        recording = load_case("indeterminate_without_reason")
        (row,) = rows_of(recording)

        receipt, api = replay_recording(recording)

        assert api.bodies == []  # asserted on the fake: validation failed before any API call
        assert not receipt.succeeded
        assert receipt.failed == 1
        assert receipt.failure is not None
        assert "reason" in receipt.failure  # the validation error
        assert str(row["subject_id"]) in receipt.failure  # naming the row by its keys


class TestRemainingRecordedCases:
    """The replay, stale, and rejection recordings hit their distinct handling paths."""

    def test_the_idempotent_replay_never_redeclares(self) -> None:
        receipt, api = replay_recording(load_case("idempotent_replay"))
        assert receipt.replayed == 1
        assert receipt.declared == 0
        assert len(api.bodies) == 1  # one submission, answered as a replay, never retried

    def test_the_out_of_order_stale_run_is_skipped_without_an_api_call(self) -> None:
        receipt, api = replay_recording(load_case("out_of_order_stale_run"))
        assert receipt.skipped_stale == 1
        assert receipt.succeeded  # skipped and counted, never an error
        assert api.bodies == []

    def test_the_illegal_transition_rejection_is_counted_and_the_run_continues(self) -> None:
        receipt, api = replay_recording(load_case("illegal_transition_rejection"))
        assert receipt.rejected == 1
        assert receipt.succeeded  # rejected is counted, not a run failure
        assert len(api.bodies) == 1  # never retried
