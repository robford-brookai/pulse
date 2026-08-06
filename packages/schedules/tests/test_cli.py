"""`schedules.cli` — task 4.1's own scenarios (spec: schedule-execution).

"Subcommands are invocable": each subcommand drives its job through the same faked boundaries
`test_month_open.py` / `test_consent_sweep.py` use, and an unknown subcommand or a missing
required argument exits nonzero with usage help before any job runs. `main`-level tests fake the
environment-wiring functions rather than the environment itself, so no socket is ever opened —
`conftest.py` would fail the test outright if one were.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from pulse_ledger.reads import SubjectState
from schedules import cli
from schedules.consent_sweep import RECONCILIATION_WRITER_ID
from schedules.month_open import FixtureEnrollmentSource, billing_episode_subject_key

MONTH_OPEN_FIXTURES = Path(__file__).parent / "fixtures"
CONSENT_SWEEP_FIXTURES = Path(__file__).parent / "fixtures" / "consent_sweep"


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(200, json={"event_id": event_id, "replayed": True})


def rejected(reason: str = "catalog rejection") -> httpx.Response:
    return httpx.Response(422, json={"detail": {"message": reason, "reason": reason}})


class ScriptedApi:
    """Same shape as `test_month_open.py` / `test_consent_sweep.py`'s own fake."""

    def __init__(self, responses: list[httpx.Response], *, writer_id: str) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses
        self._writer_id = writer_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id=self._writer_id,
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


def load_enrollments(case: str) -> tuple[date, list[SubjectState]]:
    data = json.loads((MONTH_OPEN_FIXTURES / f"{case}.json").read_text())
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


def _fake_ledger_connection() -> object:
    """Stands in for `_ledger_connection_from_env` — never actually read, since the source and
    `enumerate_state` seams above it are faked too."""
    return object()


def _fake_enumerate_state(conn: object, subject_type: str) -> list[SubjectState]:
    return []


def _ledger_state(subject_key: str, channel: str, state: str) -> SubjectState:
    return SubjectState(
        subject_type="communication_consent",
        subject_key=f"{subject_key}:{channel}",
        state=state,
        effective_at=datetime(2026, 8, 1),
        last_event_id=uuid.uuid4(),
        updated_at=datetime(2026, 8, 1),
    )


class TestMonthOpenJob:
    def test_a_normal_run_prints_the_receipt_and_exits_zero(self) -> None:
        month, enrollments = load_enrollments("normal_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([committed("e-active"), committed("e-hold")], writer_id="schedules-month-open")
        stream = io.StringIO()

        exit_code = cli.run_month_open_job(source, api.client(), month=month, stream=stream)

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["opened"] == 2
        assert receipt["invariant_breach"] is None

    def test_the_zero_enrollment_invariant_breach_exits_nonzero(self) -> None:
        month, enrollments = load_enrollments("zero_enrollment")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([], writer_id="schedules-month-open")
        stream = io.StringIO()

        exit_code = cli.run_month_open_job(source, api.client(), month=month, stream=stream)

        assert exit_code == 1
        receipt = json.loads(stream.getvalue())
        assert receipt["invariant_breach"] == "zero_enrollment"
        assert api.bodies == []

    def test_a_failed_declaration_exits_nonzero(self) -> None:
        month, enrollments = load_enrollments("mixed_outcome")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([committed("e-opens"), replayed("e-replays"), rejected()], writer_id="schedules-month-open")
        stream = io.StringIO()

        exit_code = cli.run_month_open_job(source, api.client(), month=month, stream=stream)

        assert exit_code == 1
        receipt = json.loads(stream.getvalue())
        assert receipt["failed"] == 1
        assert receipt["failed_subject_keys"] == [billing_episode_subject_key("enr-fails-1", month)]


class TestConsentSweepJob:
    def test_full_agreement_declares_nothing_and_exits_zero(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "full_agreement.csv").read_text()
        ledger_states = [
            _ledger_state("SUBJ-010", "sms", "opted_out"),
            _ledger_state("SUBJ-011", "email", "opted_in"),
        ]
        api = ScriptedApi([], writer_id=RECONCILIATION_WRITER_ID)
        stream = io.StringIO()

        exit_code = cli.run_consent_sweep_job(
            csv_text, ledger_states, api.client(), file_id="export-42", export_as_of=date(2026, 8, 5), stream=stream
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["agreements"] == 2
        assert receipt["failed_declarations"] == 0
        assert api.bodies == []

    def test_a_committed_correction_exits_zero(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text()
        api = ScriptedApi([committed()], writer_id=RECONCILIATION_WRITER_ID)
        stream = io.StringIO()

        exit_code = cli.run_consent_sweep_job(
            csv_text, [], api.client(), file_id="export-42", export_as_of=date(2026, 8, 5), stream=stream
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["opt_out_corrections"] == 1
        assert receipt["failed_declarations"] == 0

    def test_a_rejected_correction_exits_nonzero(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text()
        api = ScriptedApi([rejected()], writer_id=RECONCILIATION_WRITER_ID)
        stream = io.StringIO()

        exit_code = cli.run_consent_sweep_job(
            csv_text, [], api.client(), file_id="export-42", export_as_of=date(2026, 8, 5), stream=stream
        )

        assert exit_code == 1
        receipt = json.loads(stream.getvalue())
        assert receipt["failed_declarations"] == 1
        assert receipt["failed_subject_keys"] == ["SUBJ-001:sms"]


class TestMainDispatch:
    """`main` wired to real argv, fakes swapped in at the environment-wiring seam so no test here
    ever opens a socket (`_ledger_connection_from_env` / `_pulse_core_client_from_env`)."""

    def test_month_open_subcommand_runs_the_job_and_returns_its_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        month, enrollments = load_enrollments("normal_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        api = ScriptedApi([committed("e-active"), committed("e-hold")], writer_id="schedules-month-open")

        def fake_source(conn: object) -> FixtureEnrollmentSource:
            return source

        def fake_client(*, writer_id: str, token_env_var: str) -> PulseCoreClient:
            return api.client()

        monkeypatch.setattr(cli, "_ledger_connection_from_env", _fake_ledger_connection)
        monkeypatch.setattr(cli, "LedgerEnrollmentSource", fake_source)
        monkeypatch.setattr(cli, "_pulse_core_client_from_env", fake_client)

        exit_code = cli.main(["month-open", "--month", month.isoformat()])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["opened"] == 2

    def test_consent_sweep_subcommand_runs_the_job_and_returns_its_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export_file = tmp_path / "export.csv"
        export_file.write_text((CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text())
        api = ScriptedApi([committed()], writer_id=RECONCILIATION_WRITER_ID)

        def fake_client(*, writer_id: str, token_env_var: str) -> PulseCoreClient:
            return api.client()

        monkeypatch.setattr(cli, "_ledger_connection_from_env", _fake_ledger_connection)
        monkeypatch.setattr(cli, "enumerate_state", _fake_enumerate_state)
        monkeypatch.setattr(cli, "_pulse_core_client_from_env", fake_client)

        exit_code = cli.main([
            "consent-sweep",
            "--export-file",
            str(export_file),
            "--file-id",
            "export-42",
            "--export-as-of",
            "2026-08-05",
        ])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["opt_out_corrections"] == 1

    def test_unknown_subcommand_exits_nonzero_with_usage_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["bogus-command"])

        assert exc_info.value.code == 2
        assert "usage" in capsys.readouterr().err.lower()

    def test_missing_required_argument_exits_nonzero_with_usage_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["month-open"])

        assert exc_info.value.code == 2
        assert "usage" in capsys.readouterr().err.lower()

    def test_no_subcommand_at_all_exits_nonzero_with_usage_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli.main([])

        assert exc_info.value.code == 2
        assert "usage" in capsys.readouterr().err.lower()
