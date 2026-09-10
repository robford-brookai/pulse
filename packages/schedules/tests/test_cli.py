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
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from pulse_ledger.reads import SubjectState
from schedules import cli, sweep_production
from schedules.consent_sweep import RECONCILIATION_WRITER_ID
from schedules.month_open import FixtureEnrollmentSource, billing_episode_subject_key, load_enrollment_fixture
from schedules.projection_conformance import Comparison, ConsumerConformance, conform_family
from schedules.sweep_readers import (
    BoardReader,
    FixtureReader,
    LandingReader,
    LedgerStateReader,
    PatientsReader,
)
from twenty_projection.apply import ProjectionRestClient

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

    def test_verdict_relay_poll_subcommand_runs_the_job_and_returns_its_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`verdict-relay-poll` is fully env-driven: `main` never touches the environment itself
        here, since the wiring seam (`_verdict_relay_dependencies_from_env`) is faked — the same
        posture `_ledger_connection_from_env` / `_pulse_core_client_from_env` already have above."""
        from verdict_relay.declarer import Declarer
        from verdict_relay.mart_reader import FixtureRowSource, MartReader

        api = ScriptedApi([committed("e-poll")], writer_id="verdict-relay")
        rows = [
            {
                "subject_id": "episode-poll",
                "verdict_type": "billing_qualification",
                "outcome": "positive",
                "reason": None,
                "rule_version": "rules-v1",
                "as_of": "2026-08-01T00:00:00+00:00",
                "lineage_ref": "dbt-run-1",
                "computed_at": "2026-08-01T02:00:00+00:00",
            }
        ]

        class MemoryCursorStore:
            def load(self) -> Mapping[str, object] | None:
                return None

            def save(self, cursor: Mapping[str, object]) -> None:
                pass

        reader = MartReader(FixtureRowSource(rows), MemoryCursorStore())
        declarer = Declarer(
            api.client(),
            subject_type_by_verdict={"billing_qualification": "billing_episode"},
            sleep=lambda _s: None,
            jitter=lambda: 0.0,
        )

        def fake_dependencies() -> tuple[MartReader, Declarer]:
            return reader, declarer

        monkeypatch.setattr(cli, "_verdict_relay_dependencies_from_env", fake_dependencies)

        exit_code = cli.main(["verdict-relay-poll"])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["declared"] == 1
        assert receipt["failed"] == 0

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


class TestMonthOpenDryRunJob:
    """Task 4.2's own scenario: `run_month_open_dry_run_job` prints the would-declare set and
    exits zero, with no `PulseCoreClient` argument in its signature at all (spec: "Both jobs
    support an offline dry-run")."""

    def test_prints_the_would_declare_set_and_exits_zero(self) -> None:
        month, enrollments = load_enrollments("normal_month")
        source = FixtureEnrollmentSource(rows=enrollments)
        stream = io.StringIO()

        exit_code = cli.run_month_open_dry_run_job(source, month=month, stream=stream)

        payload = json.loads(stream.getvalue())
        assert exit_code == 0
        assert payload["dry_run"] is True
        assert payload["invariant_breach"] is None
        declared_keys = {entry["command"]["subject_key"] for entry in payload["would_declare"]}
        assert declared_keys == {
            billing_episode_subject_key("enr-active-1", month),
            billing_episode_subject_key("enr-hold-1", month),
        }

    def test_zero_enrollment_prints_the_invariant_breach_and_exits_nonzero(self) -> None:
        month, enrollments = load_enrollments("zero_enrollment")
        source = FixtureEnrollmentSource(rows=enrollments)
        stream = io.StringIO()

        exit_code = cli.run_month_open_dry_run_job(source, month=month, stream=stream)

        payload = json.loads(stream.getvalue())
        assert exit_code == 1
        assert payload["invariant_breach"] == "zero_enrollment"
        assert payload["would_declare"] == []


class TestConsentSweepDryRunJob:
    def test_prints_the_would_declare_set_and_exits_zero(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text()
        stream = io.StringIO()

        exit_code = cli.run_consent_sweep_dry_run_job(
            csv_text, [], file_id="export-42", export_as_of=date(2026, 8, 5), stream=stream
        )

        payload = json.loads(stream.getvalue())
        assert exit_code == 0
        assert payload["dry_run"] is True
        assert len(payload["would_declare"]) == 1
        assert payload["would_declare"][0]["command"]["subject_key"] == "SUBJ-001:sms"
        assert payload["unparseable"] == 0

    def test_malformed_rows_are_counted_but_never_fail_a_dry_run(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "malformed_among_valid.csv").read_text()
        ledger_states = [
            _ledger_state("SUBJ-020", "sms", "opted_out"),
            _ledger_state("SUBJ-022", "sms", "opted_in"),
        ]
        stream = io.StringIO()

        exit_code = cli.run_consent_sweep_dry_run_job(
            csv_text, ledger_states, file_id="export-42", export_as_of=date(2026, 8, 5), stream=stream
        )

        payload = json.loads(stream.getvalue())
        assert exit_code == 0
        assert payload["would_declare"] == []
        assert payload["unparseable"] == 2


class TestMainDispatchDryRun:
    """`main` wired to real argv for `--dry-run`: fakes the environment-wiring seams to raise, so
    a test failure surfaces loudly if a dry run ever reaches for a client or a ledger connection —
    exactly what the offline check command
    (`schedules.cli month-open --dry-run --fixture .../normal_month.json`) relies on to run with
    no ledger access and `--disable-socket` (spec: "Dry-run declares nothing")."""

    def _forbid_environment_wiring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _forbidden(*args: object, **kwargs: object) -> None:
            msg = "dry-run must never touch production wiring"
            raise AssertionError(msg)

        monkeypatch.setattr(cli, "_ledger_connection_from_env", _forbidden)
        monkeypatch.setattr(cli, "_pulse_core_client_from_env", _forbidden)

    def test_month_open_dry_run_with_fixture_and_no_month_derives_the_month_from_the_fixture(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._forbid_environment_wiring(monkeypatch)
        fixture_path = MONTH_OPEN_FIXTURES / "normal_month.json"
        expected_month, _ = load_enrollment_fixture(fixture_path)

        exit_code = cli.main(["month-open", "--dry-run", "--fixture", str(fixture_path)])

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert len(payload["would_declare"]) == 2
        assert all(entry["command"]["month"] == expected_month.isoformat() for entry in payload["would_declare"])

    def test_month_open_dry_run_without_fixture_exits_nonzero_with_usage_help(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._forbid_environment_wiring(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            cli.main(["month-open", "--dry-run"])

        assert exc_info.value.code == 2
        assert "usage" in capsys.readouterr().err.lower()

    def test_consent_sweep_dry_run_needs_no_ledger_fixture_at_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._forbid_environment_wiring(monkeypatch)
        export_file = tmp_path / "export.csv"
        export_file.write_text((CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text())

        exit_code = cli.main([
            "consent-sweep",
            "--dry-run",
            "--export-file",
            str(export_file),
            "--file-id",
            "export-42",
            "--export-as-of",
            "2026-08-05",
        ])

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert len(payload["would_declare"]) == 1


class TestReconcileSweepExportDiffJob:
    """`reconcile-sweep --family communication_consent`: the registry dispatches to the identical
    `export_diff` pipeline `TestConsentSweepJob` above exercises through `consent-sweep` (design.md
    decision 10) — only the printed shape (decision 7's `Receipt`) and the exit contract (0/1/2,
    decision 10) differ.
    """

    def test_full_agreement_exits_zero_and_the_receipt_is_clean(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "full_agreement.csv").read_text()
        ledger_states = [
            _ledger_state("SUBJ-010", "sms", "opted_out"),
            _ledger_state("SUBJ-011", "email", "opted_in"),
        ]
        api = ScriptedApi([], writer_id=RECONCILIATION_WRITER_ID)
        stream = io.StringIO()

        exit_code = cli.run_reconcile_export_diff_job(
            csv_text,
            ledger_states,
            api.client(),
            family="communication_consent",
            file_id="export-42",
            export_as_of=date(2026, 8, 5),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["kind"] == "export_diff"
        assert receipt["family"] == "communication_consent"
        assert receipt["consumers"][0]["agreements"] == 2
        assert receipt["consumers"][0]["divergences"] == {}
        assert receipt["failed_declarations"] == 0

    def test_a_committed_correction_is_a_named_state_divergence(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text()
        api = ScriptedApi([committed()], writer_id=RECONCILIATION_WRITER_ID)
        stream = io.StringIO()

        exit_code = cli.run_reconcile_export_diff_job(
            csv_text,
            [],
            api.client(),
            family="communication_consent",
            file_id="export-42",
            export_as_of=date(2026, 8, 5),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["consumers"][0]["divergences"] == {"state": 1}
        assert receipt["consumers"][0]["subject_keys"]["state"]["keys"] == ["SUBJ-001:sms"]
        assert receipt["consumers"][0]["subject_keys"]["state"]["total"] == 1

    def test_a_rejected_correction_exits_one_matching_the_failed_declaration_semantics(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text()
        api = ScriptedApi([rejected()], writer_id=RECONCILIATION_WRITER_ID)
        stream = io.StringIO()

        exit_code = cli.run_reconcile_export_diff_job(
            csv_text,
            [],
            api.client(),
            family="communication_consent",
            file_id="export-42",
            export_as_of=date(2026, 8, 5),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 1
        receipt = json.loads(stream.getvalue())
        assert receipt["failed_declarations"] == 1
        assert receipt["failed_subject_keys"] == ["SUBJ-001:sms"]

    def test_an_empty_export_has_nothing_to_compare_and_exits_two(self) -> None:
        stream = io.StringIO()
        api = ScriptedApi([], writer_id=RECONCILIATION_WRITER_ID)

        exit_code = cli.run_reconcile_export_diff_job(
            "subject_key,channel,suppressed\n",
            [],
            api.client(),
            family="communication_consent",
            file_id="export-42",
            export_as_of=date(2026, 8, 5),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 2
        receipt = json.loads(stream.getvalue())
        assert receipt["consumers"][0]["agreements"] == 0
        assert receipt["consumers"][0]["divergences"] == {}


class TestReconcileSweepExportDiffDryRunJob:
    def test_prints_the_receipt_and_never_declares(self) -> None:
        csv_text = (CONSENT_SWEEP_FIXTURES / "opt_out_drift.csv").read_text()
        stream = io.StringIO()

        exit_code = cli.run_reconcile_export_diff_dry_run_job(
            csv_text, [], family="communication_consent", run_date=date(2026, 9, 8), stream=stream
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["kind"] == "export_diff"
        assert receipt["consumers"][0]["divergences"] == {"state": 1}
        assert receipt["failed_declarations"] == 0


#: A resolved environment for the ledger-family dispatch tests. Values are placeholders: every
#: source is faked below, so nothing here is ever connected (`conftest.py` blocks sockets anyway).
_SWEEP_ENVIRONMENT = sweep_production.SweepEnvironment(
    pulse_core_base_url="https://pulse-core.example",
    pulse_core_token="a-read-token",  # noqa: S106 — a fixture value, not a secret
)


class _FixtureHistory:
    """A `SubjectHistorySource` over one synthetic `enrollment` subject."""

    def subject_history(self, subject_type: str, subject_key: str) -> list[Mapping[str, object]]:
        return [
            {
                "event_id": "11111111-1111-1111-1111-111111111111",
                "subject_type": subject_type,
                "subject_key": subject_key,
                "seq": 7,
                "effective_at": "2026-09-01T00:00:00+00:00",
                "recorded_at": "2026-09-01T00:00:05+00:00",
                "reverses_event_id": None,
                "payload": {"to_state": "active"},
            }
        ]


def _board_reader() -> BoardReader:
    """A real `BoardReader` over a mocked transport: one board row for `enr-1`, stored the way the
    projection stores it (`encode_option_value("active")`), so this dispatch exercises the same
    vocabulary translation a live board read does."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "patientPrograms": [
                        {"canonicalPatientId": "enr-1", "lifecycleStatus": "ACTIVE", "projectionSeq": 7}
                    ]
                }
            },
        )

    client = ProjectionRestClient(
        "https://twenty.example",
        token="a-twenty-token",  # noqa: S106 — a fixture value, not a secret
        transport=httpx.MockTransport(handler),
    )
    return BoardReader(client)


def _fixture_readers(*, patients: bool = True) -> Callable[..., sweep_production.SweepReaders]:
    """`build_sweep_readers`'s stand-in: same signature, fixture-backed readers."""

    def build(environment: sweep_production.SweepEnvironment, **kwargs: object) -> sweep_production.SweepReaders:
        del environment, kwargs
        return _sweep_readers(patients=patients)

    return build


def _sweep_readers(*, patients: bool = True) -> sweep_production.SweepReaders:
    """This environment's readers, all fixture-backed. `patients=False` is dev01: no OCEAN graph
    database, so that consumer has no reader at all."""
    rows = {"enrollment": [{"subject_key": "enr-1", "state": "active", "seq": 7}]}
    patient_rows = {"enrollment": [{"patient_id": "enr-1", "enrollment_status": "active", "ledger_seq": 7}]}
    return sweep_production.SweepReaders(
        ledger=LedgerStateReader(_FixtureHistory()),
        board=_board_reader(),
        landing=LandingReader(FixtureReader(rows_by_family=rows)),
        patients=PatientsReader(FixtureReader(rows_by_family=patient_rows)) if patients else None,
    )


class TestReconcileSweepProjectionConformanceJob:
    """`reconcile-sweep --family <ledger family>`'s receipt and exit code, over an already-built
    `FamilyConformance` (task 3.4 moved the reading itself into `sweep_production`)."""

    def test_no_registered_consumers_passes_with_no_consumers_and_exits_zero(self) -> None:
        stream = io.StringIO()

        exit_code = cli.run_reconcile_projection_conformance_job(
            conform_family(family="enrollment", snapshot={}, consumers=()),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["kind"] == "projection_conformance"
        assert receipt["no_consumers"] is True

    def test_a_family_with_zero_classified_comparisons_and_registered_consumers_exits_two(self) -> None:
        stream = io.StringIO()

        exit_code = cli.run_reconcile_projection_conformance_job(
            conform_family(
                family="enrollment",
                snapshot={},
                consumers=[ConsumerConformance(consumer="twenty-board", family="enrollment", comparisons=())],
            ),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 2

    def test_at_least_one_classified_comparison_exits_zero(self) -> None:
        stream = io.StringIO()

        exit_code = cli.run_reconcile_projection_conformance_job(
            conform_family(
                family="enrollment",
                snapshot={},
                consumers=[
                    ConsumerConformance(
                        consumer="twenty-board",
                        family="enrollment",
                        comparisons=(Comparison(subject_key="enr-1", consumer="twenty-board", outcome="agreement"),),
                    )
                ],
            ),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 0

    def test_an_unconfigured_consumer_is_named_in_the_receipt_and_is_not_a_divergence(self) -> None:
        """Design.md decision 11: skipped, named, exit unaffected — the other consumer's one
        comparison is what the exit code is about."""
        stream = io.StringIO()

        exit_code = cli.run_reconcile_projection_conformance_job(
            conform_family(
                family="enrollment",
                snapshot={},
                consumers=[
                    ConsumerConformance(
                        consumer="twenty-board",
                        family="enrollment",
                        comparisons=(Comparison(subject_key="enr-1", consumer="twenty-board", outcome="agreement"),),
                    ),
                    ConsumerConformance(consumer="graph-projection-patients", family="enrollment", unconfigured=True),
                ],
            ),
            run_date=date(2026, 9, 8),
            stream=stream,
        )

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["no_consumers"] is False
        skipped = next(c for c in receipt["consumers"] if c["consumer"] == "graph-projection-patients")
        assert skipped["unconfigured"] is True
        assert skipped["divergences"] == {}


class TestMainDispatchReconcileSweep:
    """`main` wired to real argv for `reconcile-sweep`: the registry (built from the real released
    catalog) picks the sweep kind, so these tests exercise `communication_consent` (export_diff)
    and `enrollment` (projection_conformance, no consumers registered yet) — the same two families
    `test_sweep_registry.py` pins."""

    def test_communication_consent_dispatches_the_export_diff_pipeline(
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
            "reconcile-sweep",
            "--family",
            "communication_consent",
            "--export-file",
            str(export_file),
            "--file-id",
            "export-42",
            "--export-as-of",
            "2026-08-05",
        ])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["kind"] == "export_diff"
        assert receipt["consumers"][0]["divergences"] == {"state": 1}

    def test_communication_consent_without_export_args_exits_nonzero_with_usage_help(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["reconcile-sweep", "--family", "communication_consent"])

        assert exc_info.value.code == 2
        assert "usage" in capsys.readouterr().err.lower()

    def test_a_ledger_family_builds_the_registrys_consumers_from_this_environments_readers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Task 3.4: the ledger-family path builds this run's consumers from the registry, so the
        receipt names all three — never wave 1's empty tuple, which reported `no_consumers` on
        every real run."""

        def _forbidden(*args: object, **kwargs: object) -> None:
            msg = "reconcile-sweep for a ledger family must not touch consent-sweep env wiring"
            raise AssertionError(msg)

        monkeypatch.setattr(cli, "_ledger_connection_from_env", _forbidden)
        monkeypatch.setattr(cli, "_pulse_core_client_from_env", _forbidden)
        monkeypatch.setattr(cli, "resolve_sweep_environment", lambda: _SWEEP_ENVIRONMENT)
        monkeypatch.setattr(cli, "build_sweep_readers", _fixture_readers())

        exit_code = cli.main(["reconcile-sweep", "--family", "enrollment"])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["kind"] == "projection_conformance"
        assert receipt["no_consumers"] is False
        assert [consumer["consumer"] for consumer in receipt["consumers"]] == [
            "twenty-board",
            "warehouse-landing",
            "graph-projection-patients",
        ]

    def test_a_ledger_family_names_an_unconfigured_consumer_and_still_compares_the_others(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """dev01-brook hosts no OCEAN graph database (design.md decision 11)."""
        monkeypatch.setattr(cli, "resolve_sweep_environment", lambda: _SWEEP_ENVIRONMENT)
        monkeypatch.setattr(cli, "build_sweep_readers", _fixture_readers(patients=False))

        exit_code = cli.main(["reconcile-sweep", "--family", "enrollment"])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["no_consumers"] is False
        by_name = {consumer["consumer"]: consumer for consumer in receipt["consumers"]}
        assert by_name["graph-projection-patients"]["unconfigured"] is True
        assert by_name["twenty-board"]["agreements"] == 1
        assert by_name["warehouse-landing"]["agreements"] == 1

    def test_a_missing_variable_fails_by_name_before_any_source_is_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _forbidden(*args: object, **kwargs: object) -> None:
            msg = "a source was built before the environment resolved"
            raise AssertionError(msg)

        monkeypatch.delenv(sweep_production.PULSE_CORE_BASE_URL_ENV_VAR, raising=False)
        monkeypatch.setattr(cli, "build_sweep_readers", _forbidden)

        with pytest.raises(sweep_production.MissingSweepVariableError) as exc_info:
            cli.main(["reconcile-sweep", "--family", "enrollment"])

        assert exc_info.value.name == sweep_production.PULSE_CORE_BASE_URL_ENV_VAR

    def test_an_unknown_family_exits_nonzero_with_usage_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["reconcile-sweep", "--family", "not-a-real-family"])

        assert exc_info.value.code == 2
        assert "usage" in capsys.readouterr().err.lower()
