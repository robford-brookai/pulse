"""`schedules.verdict_relay_poll` — task 3.1, spec verdict-relay-trigger.

Covers the poll's own scenarios: "A no-op poll exits clean" and "An extra run after a completed
run changes nothing", plus the no-credential-in-log posture the task also pins. The command API is
faked at the client boundary (`httpx.MockTransport`) and mart rows come from
`verdict_relay.mart_reader.FixtureRowSource`; `conftest.py` blocks sockets for every run.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator, Mapping

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from schedules.verdict_relay_poll import run_verdict_relay_poll_job
from verdict_relay.declarer import Declarer
from verdict_relay.mart_reader import FixtureRowSource, MartReader
from verdict_relay.run import configure_logging

SUBJECT_TYPE_BY_VERDICT = {"billing_qualification": "billing_episode"}

#: This scenario carries no `transition_by_outcome` entry at all — deliberately, so "no new event
#: exists" reduces to a single unambiguous count (`declared == 0`) rather than being entangled with
#: the paired-transition semantics tasks 2.1/2.2 already cover.


def mart_row(subject_id: str, *, as_of: str, computed_at: str, **overrides: object) -> dict[str, object]:
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


class ScriptedApi:
    """The command API faked at the client boundary; the last scripted response repeats."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
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
    """An in-memory `CursorStore`, shared across two `MartReader`s to model two poll invocations
    against the same durable cursor."""

    def __init__(self) -> None:
        self.saved: list[dict[str, object]] = []

    def load(self) -> Mapping[str, object] | None:
        return self.saved[-1] if self.saved else None

    def save(self, cursor: Mapping[str, object]) -> None:
        self.saved.append(dict(cursor))


def declarer_over(api: ScriptedApi, *, watermarks: dict[str, str] | None = None) -> Declarer:
    return Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        watermarks=watermarks,
        sleep=lambda _s: None,
        jitter=lambda: 0.0,
    )


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = configure_logging(stream)
    yield stream
    package_logger = logging.getLogger("verdict_relay")
    package_logger.removeHandler(handler)
    package_logger.setLevel(logging.NOTSET)


class TestNoOpPollExitsClean:
    """Scenario: a no-op poll exits clean."""

    def test_a_cursor_already_at_the_watermark_declares_nothing(self, log_stream: io.StringIO) -> None:
        store = MemoryCursorStore()
        store.saved.append({"computed_at": "2026-08-01T02:00:00+00:00", "watermarks": {}})
        rows = [mart_row("episode-A", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:00:00+00:00")]
        reader = MartReader(FixtureRowSource(rows), store)
        api = ScriptedApi([])
        declarer = declarer_over(api)
        stream = io.StringIO()

        exit_code = run_verdict_relay_poll_job(reader, declarer, stream=stream)

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt == {
            "declared": 0,
            "replayed": 0,
            "skipped_stale": 0,
            "rejected": 0,
            "transitioned": 0,
            "transition_rejected": 0,
            "failed": 0,
            "failure": None,
        }
        assert api.bodies == []  # the source was exhausted before any command was ever built


class TestExtraRunAfterACompletedRunChangesNothing:
    """Scenario: an extra run after a completed run changes nothing."""

    def test_the_second_poll_is_all_replays_and_stale_skips_with_zero_new_events(self, log_stream: io.StringIO) -> None:
        store = MemoryCursorStore()
        first_rows = [
            mart_row("episode-A", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:00:00+00:00"),
            mart_row("episode-B", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:01:00+00:00"),
        ]
        first_reader = MartReader(FixtureRowSource(first_rows), store)
        first_api = ScriptedApi([committed("e-a"), committed("e-b")])
        first_declarer = declarer_over(first_api)

        first_exit = run_verdict_relay_poll_job(first_reader, first_declarer, stream=io.StringIO())

        assert first_exit == 0
        assert first_reader.watermarks == {
            "episode-A": "2026-08-01T00:00:00+00:00",
            "episode-B": "2026-08-01T00:00:00+00:00",
        }

        # The immediate rerun: the mart republishes the same unchanged verdicts with later
        # `computed_at` stamps (an ordinary dbt re-materialization), so the reader's own
        # `computed_at` paging does not filter them out — the run-level guarantee under test is
        # that D16 replay and stale-skip absorb them, not that the reader happens to see nothing.
        second_rows = [
            mart_row("episode-A", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T03:00:00+00:00"),
            mart_row("episode-B", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T03:01:00+00:00"),
        ]
        second_reader = MartReader(FixtureRowSource(second_rows), store)
        second_api = ScriptedApi([replayed("e-a"), replayed("e-b")])
        second_declarer = declarer_over(second_api, watermarks=dict(first_reader.watermarks))
        stream = io.StringIO()

        second_exit = run_verdict_relay_poll_job(second_reader, second_declarer, stream=stream)

        assert second_exit == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["declared"] == 0  # no first-time declaration — no new event
        assert receipt["rejected"] == 0
        assert receipt["failed"] == 0
        assert receipt["replayed"] + receipt["skipped_stale"] == len(second_rows)

    def test_a_row_strictly_behind_its_watermark_is_a_stale_skip_not_an_api_call(self, log_stream: io.StringIO) -> None:
        store = MemoryCursorStore()
        # episode-C's persisted watermark is ahead of the row the second poll would otherwise see.
        watermarks = {"episode-C": "2026-08-02T00:00:00+00:00"}
        rows = [mart_row("episode-C", as_of="2026-07-01T00:00:00+00:00", computed_at="2026-08-01T02:00:00+00:00")]
        reader = MartReader(FixtureRowSource(rows), store)
        api = ScriptedApi([])
        declarer = declarer_over(api, watermarks=watermarks)
        stream = io.StringIO()

        exit_code = run_verdict_relay_poll_job(reader, declarer, stream=stream)

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["skipped_stale"] == 1
        assert receipt["declared"] == 0
        assert api.bodies == []


class TestNoCredentialValueInAnyLog:
    """Task 3.1: no credential value in any log — the printed receipt and the service's own
    structured logs never carry the token this test's fake client was constructed with."""

    def test_the_service_credential_never_appears_in_the_receipt_or_the_logs(self, log_stream: io.StringIO) -> None:
        token = "super-secret-fixture-token-never-logged"  # noqa: S105 — a fixture value, not a secret
        store = MemoryCursorStore()
        rows = [mart_row("episode-A", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-01T02:00:00+00:00")]
        reader = MartReader(FixtureRowSource(rows), store)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == f"Bearer {token}"
            return committed()

        client = PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token=token,
            transport=httpx.MockTransport(handler),
            max_attempts=1,
        )
        declarer = Declarer(
            client,
            subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
            sleep=lambda _s: None,
            jitter=lambda: 0.0,
        )
        stream = io.StringIO()

        run_verdict_relay_poll_job(reader, declarer, stream=stream)

        assert token not in stream.getvalue()
        assert token not in log_stream.getvalue()
