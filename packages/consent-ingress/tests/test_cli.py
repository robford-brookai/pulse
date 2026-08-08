"""`consent_ingress.cli` — task 4.1's own scenario: "`--dry-run` under `--disable-socket` prints
the would-declare set, exits zero, and the client fake records zero submissions."

Two boundaries are faked, the ones this package's whole test suite pins: the landing read at
`RowSource` (`FixtureRowSource`) and the command API at the client's HTTP edge
(`httpx.MockTransport`, `test_declarer.py`'s pattern). `tests/conftest.py` blocks every socket for
this module too, so a dry run that somehow reached the network would fail loudly, not silently.
"""

from __future__ import annotations

import inspect
import io
import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from consent_ingress import cli
from consent_ingress.declarer import CUSTOMERIO_WRITER_ID
from consent_ingress.row_source import FixtureRowSource
from pulse_core.client import PulseCoreClient

#: Two distinct (subject, channel) pairs, `test_declarer.py`'s own fixture rows — synthetic subject
#: keys and channel names only, no contact value.
_LANDING_ROWS: tuple[dict[str, object], ...] = (
    {
        "subject_key": "SUBJ-001",
        "channel": "email",
        "to_state": "opted_in",
        "message_id": "cio-msg-0001",
        "event_time": "2026-08-01T12:00:00+00:00",
    },
    {
        "subject_key": "SUBJ-002",
        "channel": "sms",
        "to_state": "opted_out",
        "message_id": "cio-msg-0002",
        "event_time": "2026-08-01T12:05:00+00:00",
    },
)

_LANDING_WITH_ONE_MALFORMED_ROW: tuple[dict[str, object], ...] = (
    *_LANDING_ROWS,
    {
        "subject_key": "SUBJ-003",
        "channel": "",  # empty: fails the pinned row contract
        "to_state": "opted_in",
        "message_id": "cio-msg-0003",
        "event_time": "2026-08-01T12:10:00+00:00",
    },
)


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def rejected(reason: str = "illegal transition") -> httpx.Response:
    return httpx.Response(422, json={"detail": {"message": reason, "reason": reason}})


class ScriptedApi:
    """The command API faked at the client's HTTP edge (`test_declarer.py`'s own pattern).

    Records every submitted body so a test can assert "zero submissions" directly, rather than
    inferring it from the exit code alone.
    """

    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        if self._responses is not None:
            return self._responses[min(len(self.bodies), len(self._responses)) - 1]
        return httpx.Response(201, json={"event_id": f"e{len(self.bodies)}", "replayed": False})

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id=CUSTOMERIO_WRITER_ID,
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


class NullCursorStore:
    """A never-checkpointed `CursorStore` for job-level tests that never exercise resume."""

    def load(self) -> Mapping[str, object] | None:
        return None

    def save(self, cursor: Mapping[str, object]) -> None:
        del cursor


class TestDryRunJob:
    """spec: `--dry-run` builds the full would-declare set and stops before the client."""

    def test_dry_run_prints_the_would_declare_set_and_exits_zero(self) -> None:
        source = FixtureRowSource(_LANDING_ROWS)
        stream = io.StringIO()

        exit_code = cli.run_consent_ingress_dry_run_job(source, stream=stream)

        assert exit_code == 0
        payload = json.loads(stream.getvalue())
        assert payload["dry_run"] is True
        assert payload["malformed"] == 0
        assert [entry["command"]["subject_key"] for entry in payload["would_declare"]] == [
            "SUBJ-001:email",
            "SUBJ-002:sms",
        ]
        assert [entry["command"]["command_type"] for entry in payload["would_declare"]] == [
            "record_communication_consent"
        ] * 2
        assert [entry["effective_at"] for entry in payload["would_declare"]] == [
            row["event_time"] for row in _LANDING_ROWS
        ]

    def test_malformed_rows_are_counted_but_never_fail_a_dry_run(self) -> None:
        source = FixtureRowSource(_LANDING_WITH_ONE_MALFORMED_ROW)
        stream = io.StringIO()

        exit_code = cli.run_consent_ingress_dry_run_job(source, stream=stream)

        assert exit_code == 0
        payload = json.loads(stream.getvalue())
        assert payload["malformed"] == 1
        assert len(payload["would_declare"]) == 2

    def test_dry_run_never_constructs_a_client_or_submits_anything(self) -> None:
        """The job function itself takes no client parameter at all — the strongest proof a dry
        run never reaches the command API: there is nothing here it could submit through."""

        cli.run_consent_ingress_dry_run_job(FixtureRowSource(_LANDING_ROWS), stream=io.StringIO())

        assert "client" not in inspect.signature(cli.run_consent_ingress_dry_run_job).parameters


class TestRealRunJob:
    def test_a_normal_run_declares_every_row_and_exits_zero(self) -> None:
        source = FixtureRowSource(_LANDING_ROWS)
        api = ScriptedApi([committed("e-consent-1"), committed("e-consent-2")])
        stream = io.StringIO()

        exit_code = cli.run_consent_ingress_job(source, api.client(), NullCursorStore(), stream=stream)

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["declared"] == 2
        assert receipt["rejected"] == 0
        assert len(api.bodies) == 2

    def test_a_rejected_declaration_exits_nonzero(self) -> None:
        source = FixtureRowSource(_LANDING_ROWS)
        api = ScriptedApi([committed("e-consent-1"), rejected()])
        stream = io.StringIO()

        exit_code = cli.run_consent_ingress_job(source, api.client(), NullCursorStore(), stream=stream)

        assert exit_code == 1
        receipt = json.loads(stream.getvalue())
        assert receipt["declared"] == 1
        assert receipt["rejected"] == 1

    def test_malformed_rows_are_counted_but_do_not_alone_fail_the_run(self) -> None:
        source = FixtureRowSource(_LANDING_WITH_ONE_MALFORMED_ROW)
        api = ScriptedApi()
        stream = io.StringIO()

        exit_code = cli.run_consent_ingress_job(source, api.client(), NullCursorStore(), stream=stream)

        assert exit_code == 0
        receipt = json.loads(stream.getvalue())
        assert receipt["malformed"] == 1
        assert receipt["declared"] == 2


class TestMainDispatch:
    """`main` wired to real argv, fakes swapped in at the environment-wiring seam
    (`schedules.cli`'s `TestMainDispatch` pattern) so no test here ever opens a socket."""

    def test_dry_run_via_main_never_constructs_a_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fixture_path = tmp_path / "landing.json"
        fixture_path.write_text(json.dumps(list(_LANDING_ROWS)))

        def _forbidden(*_args: object, **_kwargs: object) -> PulseCoreClient:
            msg = "a dry run must never construct a PulseCoreClient"
            raise AssertionError(msg)

        monkeypatch.setattr(cli, "PulseCoreClient", _forbidden)

        exit_code = cli.main(["--dry-run", "--landing-fixture", str(fixture_path)])

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert len(payload["would_declare"]) == 2

    def test_a_real_run_via_main_wires_the_client_and_cursor_store_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fixture_path = tmp_path / "landing.json"
        fixture_path.write_text(json.dumps(list(_LANDING_ROWS)))
        api = ScriptedApi([committed("e-consent-1"), committed("e-consent-2")])

        def _fake_client(*_args: object, **_kwargs: object) -> PulseCoreClient:
            return api.client()

        def _fake_cursor_store(*_args: object, **_kwargs: object) -> NullCursorStore:
            return NullCursorStore()

        monkeypatch.setenv(cli.PULSE_CORE_BASE_URL_ENV_VAR, "http://ledger.test")
        monkeypatch.setenv(cli.CUSTOMERIO_TOKEN_ENV_VAR, "unit-test-token")
        monkeypatch.setenv(cli.CURSOR_TOKEN_ENV_VAR, "unit-test-token")
        monkeypatch.setattr(cli, "PulseCoreClient", _fake_client)
        monkeypatch.setattr(cli, "LedgerCursorStore", _fake_cursor_store)

        exit_code = cli.main(["--landing-fixture", str(fixture_path)])

        assert exit_code == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["declared"] == 2
        assert len(api.bodies) == 2

    def test_missing_landing_fixture_argument_exits_nonzero_with_usage_help(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--dry-run"])

        assert exc_info.value.code == 2
        assert "landing-fixture" in capsys.readouterr().err
