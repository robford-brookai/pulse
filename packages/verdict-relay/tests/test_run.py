"""`verdict_relay.run` — batch entrypoint: read → declare → receipt (task 3.1; seven counts, billing-state 2.4).

Covers the verdict-relay-run scenario "A mixed batch produces a complete receipt": seven counts —
declared, replayed, skipped-stale, rejected, transitioned, transition-rejected, failed — as
structured JSON logs tagged `service:verdict-relay` with one Datadog-parsable `key=value` summary
line in the pinned form, the no-PHI log lint (records carry subject keys only, design decision 6),
and nonzero exit on run failure with the receipt reflecting completed work.

The command API is faked at the client boundary (`httpx.MockTransport`) and mart rows come from
`FixtureRowSource`; `conftest.py` blocks sockets for every run.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator, Mapping
from typing import cast

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from verdict_relay.declarer import Declarer
from verdict_relay.mart_reader import FixtureRowSource, MartReader
from verdict_relay.run import SERVICE, RunReceipt, configure_logging, main, run_relay

SUBJECT_TYPE_BY_VERDICT = {"billing_qualification": "billing_episode"}

#: Only `positive` pairs a transition, so a replayed `negative` verdict submits the verdict alone.
TRANSITION_BY_OUTCOME = {"billing_qualification": {"positive": "qualified"}}


def mart_row(subject_id: str, *, as_of: str, computed_at: str, **overrides: object) -> dict[str, object]:
    """One synthetic mart-contract row; keyword overrides mutate nothing shared."""
    row: dict[str, object] = {
        "subject_id": subject_id,
        "verdict_type": "billing_qualification",
        "outcome": "positive",
        "reason": None,
        "rule_version": "rules-v3",
        "as_of": as_of,
        "lineage_ref": f"dbt-run-{computed_at}",
        "computed_at": computed_at,
    }
    row.update(overrides)
    return row


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": True})


def rejected() -> httpx.Response:
    return httpx.Response(
        422,
        json={
            "detail": {
                "message": "verdict regresses the subject's state",
                "reason": "illegal transition",
                "catalog_version": "appendix-c-v0.7",
            }
        },
    )


def transient() -> httpx.Response:
    return httpx.Response(503, text="upstream unavailable")


class ScriptedApi:
    """The command API faked at the client boundary; the last scripted response repeats."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
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
    """An in-memory `CursorStore`; `saved` records every commit for assertions."""

    def __init__(self) -> None:
        self.saved: list[dict[str, object]] = []

    def load(self) -> Mapping[str, object] | None:
        return self.saved[-1] if self.saved else None

    def save(self, cursor: Mapping[str, object]) -> None:
        self.saved.append(dict(cursor))


def declarer_over(
    api: ScriptedApi,
    *,
    watermarks: dict[str, str] | None = None,
    transition_by_outcome: dict[str, dict[str, str]] | None = None,
) -> Declarer:
    return Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        transition_by_outcome=transition_by_outcome,
        watermarks=watermarks,
        sleep=lambda _s: None,
        jitter=lambda: 0.0,
    )


def mixed_batch() -> list[dict[str, object]]:
    """A paired declare, a replay, a stale row, a verdict rejection, and a transition rejection."""
    return [
        mart_row("episode-A", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:00:00+00:00"),
        mart_row(
            "episode-B",
            as_of="2026-08-01T00:00:00+00:00",
            computed_at="2026-08-01T02:01:00+00:00",
            outcome="negative",
        ),
        mart_row("episode-C", as_of="2026-07-01T00:00:00+00:00", computed_at="2026-08-01T02:02:00+00:00"),
        mart_row("episode-D", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:03:00+00:00"),
        mart_row("episode-E", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:04:00+00:00"),
    ]


#: Reader order is (subject, as_of): A declares and its paired transition commits, B replays
#: (outcome unmapped, no transition), C is stale (no API call), D's verdict rejects, E declares
#: and its paired transition is refused at a lifecycle boundary.
MIXED_RESPONSES = [committed(), committed("t1"), replayed(), rejected(), committed("e2"), rejected()]

#: episode-C's persisted watermark is ahead of its row's as_of, making that row stale.
MIXED_WATERMARKS = {"episode-C": "2026-08-02T00:00:00+00:00"}


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """The service's JSON log handler over a capturable stream, detached after the test."""
    stream = io.StringIO()
    handler = configure_logging(stream)
    yield stream
    package_logger = logging.getLogger("verdict_relay")
    package_logger.removeHandler(handler)
    package_logger.setLevel(logging.NOTSET)


def log_records(stream: io.StringIO) -> list[dict[str, object]]:
    return [cast("dict[str, object]", json.loads(line)) for line in stream.getvalue().splitlines()]


def summary_lines(records: list[dict[str, object]]) -> list[str]:
    return [str(r["message"]) for r in records if str(r["message"]).startswith(f"service={SERVICE} result=")]


def parse_summary(line: str) -> dict[str, str]:
    return dict(pair.split("=", 1) for pair in line.split(" "))


class TestMixedBatchScenario:
    """Scenario: a mixed batch produces a complete receipt."""

    def run_mixed_batch(self) -> RunReceipt:
        api = ScriptedApi(MIXED_RESPONSES)
        reader = MartReader(FixtureRowSource(mixed_batch()), MemoryCursorStore())
        declarer = declarer_over(
            api,
            watermarks=dict(MIXED_WATERMARKS),
            transition_by_outcome=TRANSITION_BY_OUTCOME,
        )
        return run_relay(reader, declarer)

    def test_the_receipt_reports_all_seven_counts(self, log_stream: io.StringIO) -> None:
        receipt = self.run_mixed_batch()

        assert receipt.declared == 2
        assert receipt.replayed == 1
        assert receipt.skipped_stale == 1
        assert receipt.rejected == 1
        assert receipt.transitioned == 1
        assert receipt.transition_rejected == 1
        assert receipt.failed == 0
        assert receipt.succeeded

    def test_exactly_one_summary_line_in_the_pinned_form(self, log_stream: io.StringIO) -> None:
        self.run_mixed_batch()

        (line,) = summary_lines(log_records(log_stream))
        # The spec pins the exact form, key order included — assert the whole line, not a parse.
        assert line == (
            f"service={SERVICE} result=success declared=2 replayed=1 skipped_stale=1 "
            "rejected=1 transitioned=1 transition_rejected=1 failed=0"
        )

    def test_every_record_is_structured_json_tagged_with_the_service(self, log_stream: io.StringIO) -> None:
        self.run_mixed_batch()

        records = log_records(log_stream)
        assert records  # the run logged, and every line parsed as JSON
        for record in records:
            assert record["service"] == SERVICE
            assert {"timestamp", "level", "logger", "message"} <= set(record)

    def test_the_run_commits_page_position_and_watermarks_once_per_page(self, log_stream: io.StringIO) -> None:
        api = ScriptedApi(MIXED_RESPONSES)
        store = MemoryCursorStore()
        reader = MartReader(FixtureRowSource(mixed_batch()), store)
        declarer = declarer_over(
            api,
            watermarks=dict(MIXED_WATERMARKS),
            transition_by_outcome=TRANSITION_BY_OUTCOME,
        )

        run_relay(reader, declarer)

        (cursor,) = store.saved
        assert cursor["computed_at"] == "2026-08-01T02:04:00+00:00"
        # Declared and replayed rows advance the persisted watermark; stale and rejected do not,
        # and a refused paired transition leaves its verdict's watermark advance standing.
        assert cursor["watermarks"] == {
            "episode-A": "2026-08-01T00:00:00+00:00",
            "episode-B": "2026-08-01T00:00:00+00:00",
            "episode-E": "2026-08-01T00:00:00+00:00",
        }


class TestNoPhiLogLint:
    """Design decision 6: records carry subject keys only — never demographics, never outcomes."""

    DEMOGRAPHIC_MARKERS = (
        "first_name",
        "last_name",
        "full_name",
        "date_of_birth",
        "dob",
        "ssn",
        "address",
        "phone",
        "email",
        "mrn",
        "zip_code",
    )
    OUTCOME_VALUES = ("positive", "negative", "indeterminate")

    def test_log_records_carry_subject_keys_only(self, log_stream: io.StringIO) -> None:
        api = ScriptedApi(MIXED_RESPONSES)
        reader = MartReader(FixtureRowSource(mixed_batch()), MemoryCursorStore())
        declarer = declarer_over(
            api,
            watermarks=dict(MIXED_WATERMARKS),
            transition_by_outcome=TRANSITION_BY_OUTCOME,
        )

        run_relay(reader, declarer)

        output = log_stream.getvalue().lower()
        assert "episode-" in output  # rows are named by subject key
        for marker in self.DEMOGRAPHIC_MARKERS:
            assert marker not in output
        for outcome in self.OUTCOME_VALUES:
            assert outcome not in output


class TestFailedRun:
    """Spec: a failed run exits nonzero with the receipt reflecting completed work."""

    def failing_batch(self) -> tuple[MartReader, Declarer, MemoryCursorStore]:
        # episode-A commits, then episode-B is transient forever: the attempt budget exhausts.
        api = ScriptedApi([committed(), transient()])
        store = MemoryCursorStore()
        reader = MartReader(FixtureRowSource(mixed_batch()[:2]), store)
        return reader, declarer_over(api), store

    def test_the_receipt_reflects_work_completed_before_the_failure(self, log_stream: io.StringIO) -> None:
        reader, declarer, store = self.failing_batch()

        receipt = run_relay(reader, declarer)

        assert not receipt.succeeded
        assert receipt.declared == 1  # episode-A finished before episode-B failed
        assert receipt.failed == 1
        assert receipt.failure is not None
        assert "episode-B" in receipt.failure  # the failure names the row by its keys
        assert store.saved == []  # the failed page is not committed; the resumed run re-reads it

    def test_the_failed_run_still_emits_the_summary_line(self, log_stream: io.StringIO) -> None:
        reader, declarer, _store = self.failing_batch()

        run_relay(reader, declarer)

        (line,) = summary_lines(log_records(log_stream))
        parsed = parse_summary(line)
        assert parsed["result"] == "failure"
        assert parsed["declared"] == "1"
        assert parsed["transitioned"] == "0"
        assert parsed["transition_rejected"] == "0"
        assert parsed["failed"] == "1"

    def test_a_contract_violation_fails_the_run_naming_the_row(self, log_stream: io.StringIO) -> None:
        bad_row = mart_row("episode-A", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:00:00+00:00")
        del bad_row["rule_version"]
        reader = MartReader(FixtureRowSource([bad_row]), MemoryCursorStore())

        receipt = run_relay(reader, declarer_over(ScriptedApi([committed()])))

        assert not receipt.succeeded
        assert receipt.failed == 1
        assert receipt.failure is not None
        assert "rule_version" in receipt.failure


class TestExitCode:
    def test_a_successful_run_exits_zero(self) -> None:
        api = ScriptedApi(MIXED_RESPONSES)
        reader = MartReader(FixtureRowSource(mixed_batch()), MemoryCursorStore())
        declarer = declarer_over(
            api,
            watermarks=dict(MIXED_WATERMARKS),
            transition_by_outcome=TRANSITION_BY_OUTCOME,
        )

        assert main(reader, declarer, stream=io.StringIO()) == 0

    def test_a_failed_run_exits_nonzero(self) -> None:
        api = ScriptedApi([committed(), transient()])
        reader = MartReader(FixtureRowSource(mixed_batch()[:2]), MemoryCursorStore())

        assert main(reader, declarer_over(api), stream=io.StringIO()) == 1

    def test_main_detaches_its_handler_after_the_run(self) -> None:
        api = ScriptedApi(MIXED_RESPONSES)
        reader = MartReader(FixtureRowSource(mixed_batch()), MemoryCursorStore())
        declarer = declarer_over(
            api,
            watermarks=dict(MIXED_WATERMARKS),
            transition_by_outcome=TRANSITION_BY_OUTCOME,
        )
        before = list(logging.getLogger("verdict_relay").handlers)

        main(reader, declarer, stream=io.StringIO())

        assert logging.getLogger("verdict_relay").handlers == before
