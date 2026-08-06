"""`schedules.month_open` — task 2.1's two scenarios (spec: month-open).

"Normal month-open": month-open declares exactly the active/on-hold set from a recorded
enumeration that also holds an `ended` enrollment, which gets none. "A state-name typo rejects the
run": an unknown state name in the requested set fails via the catalog rejection, with zero
commands submitted.

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
