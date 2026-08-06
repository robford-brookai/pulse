"""`schedules.month_open` — task 2.1's two scenarios plus task 2.2's re-run scenarios (spec:
month-open).

"Normal month-open": month-open declares exactly the active/on-hold set from a recorded
enumeration that also holds an `ended` enrollment, which gets none. "A state-name typo rejects the
run": an unknown state name in the requested set fails via the catalog rejection, with zero
commands submitted. "Re-run replays": a second run over the same enumeration classifies every
declaration `replayed`, deriving the identical D16 key it derived the first time, because
`logical_time` is the billing month's first-of-month instant — never "now" — so it is stable
across calls regardless of which day either call happens to run on. "Mid-month invocation": a run
on the 15th replays the two enrollments already opened on the 1st and opens the one enrollment
that activated on the 10th, with every command's `effective_at` pinned to the 1st regardless of
the run's own day.

The command API is faked at the client boundary (`httpx.MockTransport` under a real
`PulseCoreClient`, per verdict-relay's pattern) and the ledger read at the `enumerate_state`
boundary (`FixtureEnrollmentSource` / the real `LedgerEnrollmentSource` against a catalog-only
validation path); `conftest.py` blocks sockets for every run.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import cast

import httpx
import psycopg
import pytest
from pulse_core.client import PulseCoreClient
from pulse_ledger.reads import SubjectState
from pulse_ledger.validation import IllegalTransitionError
from schedules.month_open import (
    FixtureEnrollmentSource,
    LedgerEnrollmentSource,
    billing_episode_subject_key,
    billing_month_effective_at,
    declare_month_open,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_enrollments(case: str) -> tuple[date, list[SubjectState]]:
    """A recorded `enumerate_state` response, per fixture (design decision 9)."""
    data = json.loads((FIXTURES / f"{case}.json").read_text())
    month = date.fromisoformat(data["month"])
    rows = [
        SubjectState(
            subject_type="enrollment",
            subject_key=row["subject_key"],
            state=row["state"],
            effective_at=datetime.fromisoformat(row["effective_at"]),
            last_event_id=uuid.UUID(row["last_event_id"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in data["enrollments"]
    ]
    return month, rows


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": True})


class ScriptedApi:
    """The command API faked at the client boundary: scripted answers, recorded request bodies."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="schedules-month-open",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


class TestNormalMonthOpen:
    def test_declares_exactly_the_active_and_on_hold_set(self) -> None:
        month, enrollments = load_enrollments("normal_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([committed("e-active"), committed("e-hold")])

        declarations = declare_month_open(source, api.client(), month=month)

        assert {declaration.enrollment.subject_key for declaration in declarations} == {
            "enr-active-1",
            "enr-hold-1",
        }
        assert len(api.bodies) == 2

    def test_ended_enrollments_get_no_declaration(self) -> None:
        month, enrollments = load_enrollments("normal_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([committed(), committed()])

        declarations = declare_month_open(source, api.client(), month=month)

        assert "enr-ended-1" not in {declaration.enrollment.subject_key for declaration in declarations}
        assert all(body["subject_type"] == "billing_episode" for body in api.bodies)
        assert {body["subject_key"] for body in api.bodies} == {
            billing_episode_subject_key("enr-active-1", month),
            billing_episode_subject_key("enr-hold-1", month),
        }

    def test_declares_one_open_billing_episode_command_per_enrollment(self) -> None:
        month, enrollments = load_enrollments("normal_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([committed(), committed()])

        declarations = declare_month_open(source, api.client(), month=month)

        for declaration in declarations:
            assert declaration.command.command_type == "open_billing_episode"
            assert declaration.command.month == month
            assert declaration.command.subject_key == billing_episode_subject_key(
                declaration.enrollment.subject_key, month
            )
            assert declaration.response.classification.value == "committed"


class TestStateNameTypoRejectsTheRun:
    def test_unknown_state_name_fails_with_no_commands_declared(self) -> None:
        # Catalog validation runs inside `enumerate_state` before any query executes, so the
        # typo'd state raises without ever touching `conn` — a sentinel stands in for it, per
        # `pulse_ledger.reads.enumerate_state`'s own validate-then-query ordering.
        source = LedgerEnrollmentSource(conn=cast("psycopg.Connection", object()))
        api = ScriptedApi([])

        with pytest.raises(IllegalTransitionError):
            declare_month_open(source, api.client(), month=date(2026, 8, 1), states=("active", "on_hold_typo"))

        assert api.bodies == []


class TestReRunReplays:
    def test_same_day_rerun_classifies_every_declaration_replayed_with_no_second_episode(self) -> None:
        month, enrollments = load_enrollments("rerun_month")
        source = FixtureEnrollmentSource(rows=enrollments)

        first_run_api = ScriptedApi([committed("e-active"), committed("e-hold")])
        first_run = declare_month_open(source, first_run_api.client(), month=month)
        assert {declaration.response.classification.value for declaration in first_run} == {"committed"}

        second_run_api = ScriptedApi([replayed("e-active"), replayed("e-hold")])
        second_run = declare_month_open(source, second_run_api.client(), month=month)

        assert {declaration.response.classification.value for declaration in second_run} == {"replayed"}
        # The same enumeration declares the same episode subject_key both times — a replay, not a
        # second episode for the same enrollment x month.
        assert {declaration.command.subject_key for declaration in first_run} == {
            declaration.command.subject_key for declaration in second_run
        }
        # The D16 idempotency key the client derived is identical run to run: same writer, same
        # subject, same payload, same `logical_time` — the ledger has no way to tell the second
        # call apart from a retry of the first.
        assert [body["idempotency_key"] for body in first_run_api.bodies] == [
            body["idempotency_key"] for body in second_run_api.bodies
        ]


class TestMidMonthInvocation:
    def test_replays_existing_episodes_and_opens_only_the_newly_activated_enrollment(self) -> None:
        month, enrollments = load_enrollments("mid_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        # Enumeration order is the fixture's own order: the two enrollments opened on the 1st,
        # then the one that activated on the 10th — so the API script mirrors that order.
        api = ScriptedApi([replayed("e-active"), replayed("e-hold"), committed("e-active-2")])

        declarations = declare_month_open(source, api.client(), month=month)

        by_subject_key = {declaration.enrollment.subject_key: declaration for declaration in declarations}
        assert by_subject_key["enr-active-1"].response.classification.value == "replayed"
        assert by_subject_key["enr-hold-1"].response.classification.value == "replayed"
        assert by_subject_key["enr-active-2"].response.classification.value == "committed"

        # `month` here is the 15th — the run's own invocation day, per the fixture — yet every
        # declaration's `effective_at` (and therefore `logical_time`) is pinned to the billing
        # month's first, never the day the job happened to run (spec: "Month-open is safely
        # re-runnable any day of the month").
        expected_effective_at = billing_month_effective_at(month).isoformat()
        assert month.day != 1
        assert all(body["effective_at"] == expected_effective_at for body in api.bodies)
