"""Smoke-parse and harness-unit tests for Demo 5 (task 2.1).

`scripts/demo/demo5_end_to_end.py` needs the LocalStack + Postgres compose stack, so per the
roadmap's demo convention it stays out of `task check`'s own run. Two things do run under `check`:

- The smoke-parse contract every demo script holds (`test_demo1_ledger_core.py`'s precedent):
  the script imports cleanly with no I/O, its argument parser builds, and `--help` exits cleanly.
- A unit test of the harness loop itself (`run_walk`), against two fake `Stage` implementations —
  no compose stack, no ledger, no fixtures — asserting stop-on-first-failure and the receipt shape
  the spec pins ("a receipt naming each stage, its assertion count, and the subject keys it
  touched").
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo5_end_to_end.py"

spec = importlib.util.spec_from_file_location("demo5_end_to_end", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo5 = importlib.util.module_from_spec(spec)
sys.modules["demo5_end_to_end"] = demo5
spec.loader.exec_module(demo5)


# --- Smoke-parse contract -------------------------------------------------------------------------


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_an_argument_parser() -> None:
    assert isinstance(demo5.build_arg_parser(), argparse.ArgumentParser)


def test_default_args_parse_with_no_arguments() -> None:
    args = demo5.build_arg_parser().parse_args([])
    assert args.skip_compose_up is False
    assert args.live is False
    assert "ledger" in args.database_url


def test_help_exits_cleanly_with_no_network_or_stack() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_stages_are_wired_in_spec_order() -> None:
    names = [stage.name for stage in demo5.STAGES]
    assert names == [
        "identity_resolution",
        "consent_ingress",
        "board_drag",
        "verdict_declare",
        "window_agreement",
        "rebuild_drill",
    ]


def test_from_stage_defaults_to_the_whole_walk() -> None:
    args = demo5.build_arg_parser().parse_args([])
    assert args.from_stage is None
    assert demo5.stages_from(None) == demo5.STAGES


def test_from_stage_keeps_the_suffix_in_spec_order() -> None:
    args = demo5.build_arg_parser().parse_args(["--from-stage", "window_agreement"])
    names = [stage.name for stage in demo5.stages_from(args.from_stage)]
    assert names == ["window_agreement", "rebuild_drill"]


def test_from_stage_rejects_an_unknown_stage_name() -> None:
    with pytest.raises(SystemExit):
        demo5.build_arg_parser().parse_args(["--from-stage", "nope"])
    with pytest.raises(ValueError, match="unknown stage"):
        demo5.stages_from("nope")


# --- Harness unit tests: run_walk over fake stages -------------------------------------------------


class _FakeStage:
    """A minimal `Stage`: records whether `setup`/`run` were called, optionally fails."""

    def __init__(
        self, name: str, *, fail: bool = False, assertion_count: int = 1, subject_keys: tuple[str, ...] = ()
    ) -> None:
        self.name = name
        self._fail = fail
        self._assertion_count = assertion_count
        self._subject_keys = subject_keys
        self.setup_called = False
        self.run_called = False

    def setup(self, ctx: object) -> None:
        del ctx
        self.setup_called = True

    def run(self, ctx: object) -> object:
        del ctx
        self.run_called = True
        if self._fail:
            message = f"{self.name} deliberately failed"
            raise demo5.DemoAssertionError(message)
        return demo5.StageReceipt(self.name, assertion_count=self._assertion_count, subject_keys=self._subject_keys)


def test_run_walk_returns_a_receipt_per_stage_in_order() -> None:
    stages = [
        _FakeStage("first", assertion_count=2, subject_keys=("patient-1",)),
        _FakeStage("second", assertion_count=3, subject_keys=("patient-1", "episode-1")),
    ]
    receipts = demo5.run_walk(stages, ctx=object())

    assert [r.stage for r in receipts] == ["first", "second"]
    assert receipts[0].assertion_count == 2
    assert receipts[0].subject_keys == ("patient-1",)
    assert receipts[1].assertion_count == 3
    assert receipts[1].subject_keys == ("patient-1", "episode-1")
    assert all(stage.setup_called and stage.run_called for stage in stages)


def test_run_walk_stops_on_first_failure_and_never_runs_later_stages() -> None:
    first = _FakeStage("first")
    failing = _FakeStage("failing", fail=True)
    never_runs = _FakeStage("never_runs")

    with pytest.raises(demo5.StageFailure) as excinfo:
        demo5.run_walk([first, failing, never_runs], ctx=object())

    assert excinfo.value.stage_name == "failing"
    assert "deliberately failed" in excinfo.value.message
    assert first.run_called is True
    assert failing.run_called is True
    assert never_runs.setup_called is False
    assert never_runs.run_called is False


def test_stage_receipt_shape() -> None:
    receipt = demo5.StageReceipt("a_stage", assertion_count=5, subject_keys=("k1", "k2"))
    assert receipt.stage == "a_stage"
    assert receipt.assertion_count == 5
    assert receipt.subject_keys == ("k1", "k2")


def test_print_receipt_does_not_raise_on_an_empty_or_populated_list(capsys: pytest.CaptureFixture[str]) -> None:
    demo5.print_receipt([])
    demo5.print_receipt([demo5.StageReceipt("a_stage", assertion_count=1, subject_keys=("k1",))])
    captured = capsys.readouterr()
    assert "Demo 5 receipt" in captured.out
    assert "a_stage" in captured.out


# --- Live config: resolve_live_config, no I/O -------------------------------------------------

_LIVE_ENV: dict[str, str] = {
    demo5.DATABASE_URL_ENV: "postgresql://ledger:changeme@localhost:5434/ledger",
    demo5.LEDGER_URL_ENV: "https://ledger.dev.example",
    demo5.TWENTY_WEBHOOK_SECRET_ENV: "a-webhook-secret",
    "PULSE_TWENTY_DEV_URL": "https://twenty.dev.example",
    "PULSE_TWENTY_DEV_TOKEN": "a-twenty-token",
    demo5.CUSTOMERIO_TOKEN_ENV_VAR: "a-customerio-token",
    demo5.VERDICT_RELAY_TOKEN_ENV_VAR: "a-verdict-relay-token",
    demo5.REPLAY_TOKEN_ENV_VAR: "a-replay-token",
    demo5.STG_EVENTS_ACCOUNT_ENV: "an-account",
    demo5.STG_EVENTS_USER_ENV: "a-user",
    demo5.STG_EVENTS_PASSWORD_ENV: "a-password",
    demo5.STG_EVENTS_WAREHOUSE_ENV: "a-warehouse",
}


def test_resolve_live_config_reads_every_credential_by_name() -> None:
    config = demo5.resolve_live_config(_LIVE_ENV)
    assert config.database_url == _LIVE_ENV[demo5.DATABASE_URL_ENV]
    assert config.ledger_url == _LIVE_ENV[demo5.LEDGER_URL_ENV]
    assert config.webhook_secret == _LIVE_ENV[demo5.TWENTY_WEBHOOK_SECRET_ENV]
    assert config.twenty_target.url == _LIVE_ENV["PULSE_TWENTY_DEV_URL"]
    assert config.twenty_target.token == _LIVE_ENV["PULSE_TWENTY_DEV_TOKEN"]
    assert config.customerio_token == _LIVE_ENV[demo5.CUSTOMERIO_TOKEN_ENV_VAR]
    assert config.verdict_relay_token == _LIVE_ENV[demo5.VERDICT_RELAY_TOKEN_ENV_VAR]
    assert config.projection_replay_token == _LIVE_ENV[demo5.REPLAY_TOKEN_ENV_VAR]
    assert config.snowflake_account == _LIVE_ENV[demo5.STG_EVENTS_ACCOUNT_ENV]
    assert config.snowflake_password == _LIVE_ENV[demo5.STG_EVENTS_PASSWORD_ENV]
    assert config.snowflake_private_key_path is None


def test_resolve_live_config_accepts_a_private_key_path_in_lieu_of_a_password() -> None:
    env = {k: v for k, v in _LIVE_ENV.items() if k != demo5.STG_EVENTS_PASSWORD_ENV}
    env[demo5.STG_EVENTS_PRIVATE_KEY_PATH_ENV] = "/path/to/key.pem"
    config = demo5.resolve_live_config(env)
    assert config.snowflake_password is None
    assert config.snowflake_private_key_path == "/path/to/key.pem"


@pytest.mark.parametrize("missing", sorted(_LIVE_ENV))
def test_resolve_live_config_refuses_on_the_first_missing_variable(missing: str) -> None:
    env = {k: v for k, v in _LIVE_ENV.items() if k != missing}
    if missing == demo5.STG_EVENTS_PASSWORD_ENV:
        # The password/private-key pair is either/or — dropping the password alone is not a
        # refusal (the private-key path is still set), covered by its own test above.
        return
    with pytest.raises(demo5.LiveStartupError) as excinfo:
        demo5.resolve_live_config(env)
    # A `PULSE_TWENTY_DEV_*` variable is named through `resolve_target`'s own `DeployError`
    # message rather than bare, so match on containment for those two.
    assert any(missing in item for item in excinfo.value.missing)


def test_resolve_live_config_refuses_when_neither_snowflake_credential_is_set() -> None:
    env = {k: v for k, v in _LIVE_ENV.items() if k != demo5.STG_EVENTS_PASSWORD_ENV}
    with pytest.raises(demo5.LiveStartupError) as excinfo:
        demo5.resolve_live_config(env)
    assert any("SNOWFLAKE" in name for name in excinfo.value.missing)


def test_resolve_live_config_refuses_an_unknown_twenty_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo5, "TWENTY_TARGET", "not-a-real-target")
    with pytest.raises(demo5.LiveStartupError):
        demo5.resolve_live_config(_LIVE_ENV)


# --- Live warehouse window: _fetch_stg_events over a fake Snowflake connection ------------------


class _FakeSnowflakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.executed: tuple[str, list[Any]] | None = None

    def execute(self, query: str, params: list[Any]) -> None:
        self.executed = (query, params)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def close(self) -> None:
        pass


class _FakeSnowflakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._cursor = _FakeSnowflakeCursor(rows)
        self.closed = False

    def cursor(self) -> _FakeSnowflakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _stg_events_row(
    *, event_id: str = "evt-1", subject_type: str = "enrollment", subject_key: str = "pt-0001"
) -> tuple[Any, ...]:
    return (
        event_id,
        subject_type,
        subject_key,
        "2026-08-27T00:00:00+00:00",
        "2026-08-27T00:00:01+00:00",
        None,
        {"to_state": "active"},
    )


def test_fetch_stg_events_groups_rows_by_subject_and_closes_the_connection() -> None:
    connection = _FakeSnowflakeConnection([_stg_events_row()])
    result = demo5._fetch_stg_events(
        frozenset({("enrollment", "pt-0001"), ("billing_episode", "ep-0001")}),
        connect=lambda: connection,
    )
    assert result[("enrollment", "pt-0001")][0]["event_id"] == "evt-1"
    assert result[("billing_episode", "ep-0001")] == []
    assert connection.closed is True


def test_fetch_stg_events_decodes_a_variant_payload_delivered_as_json_text() -> None:
    # snowflake-connector hands a VARIANT column back as its JSON text; the fold needs a mapping.
    row = (*_stg_events_row()[:-1], '{"to_state": "active", "channel": "email"}')
    connection = _FakeSnowflakeConnection([row])
    result = demo5._fetch_stg_events(frozenset({("enrollment", "pt-0001")}), connect=lambda: connection)
    assert result[("enrollment", "pt-0001")][0]["payload"] == {"to_state": "active", "channel": "email"}


def test_fetch_stg_events_renders_timestamp_tz_datetimes_as_iso_text() -> None:
    # snowflake-connector hands TIMESTAMP_TZ back as tz-aware datetimes; the fold parses ISO text.
    from datetime import UTC, datetime

    row = list(_stg_events_row())
    row[3], row[4] = datetime(2026, 8, 27, tzinfo=UTC), datetime(2026, 8, 27, 0, 0, 1, tzinfo=UTC)
    connection = _FakeSnowflakeConnection([tuple(row)])
    result = demo5._fetch_stg_events(frozenset({("enrollment", "pt-0001")}), connect=lambda: connection)
    event = result[("enrollment", "pt-0001")][0]
    assert event["effective_at"] == "2026-08-27T00:00:00+00:00"
    assert datetime.fromisoformat(event["recorded_at"]) == row[4]


def test_fetch_stg_events_drops_a_row_for_an_unwanted_subject() -> None:
    connection = _FakeSnowflakeConnection([_stg_events_row(subject_key="not-in-scope")])
    result = demo5._fetch_stg_events(frozenset({("enrollment", "pt-0001")}), connect=lambda: connection)
    assert result[("enrollment", "pt-0001")] == []


def test_fetch_stg_events_never_connects_for_an_empty_subject_set() -> None:
    def _fail_to_connect() -> Any:
        pytest.fail("connect() should never be called for an empty subject set")

    result = demo5._fetch_stg_events(frozenset(), connect=_fail_to_connect)
    assert result == {}


# --- Live context builder: build_live_context, no live Postgres or network ---------------------


class _FakePool:
    """Stands in for `psycopg_pool.ConnectionPool` — `build_live_context` only calls `.wait()` and
    registers `.close()` before this test ever runs a stage against it."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.waited = False
        self.closed = False

    def wait(self) -> None:
        self.waited = True

    def close(self) -> None:
        self.closed = True


def test_build_live_context_wires_credentials_and_never_touches_a_live_stack() -> None:
    config = demo5.resolve_live_config(_LIVE_ENV)
    ctx = demo5.build_live_context(config, pool_factory=_FakePool)
    try:
        assert ctx.live is True
        assert ctx.api_transport is None
        assert ctx.api_base_url == config.ledger_url
        assert ctx.webhook_secret == config.webhook_secret
        assert ctx.writer_tokens[demo5.CUSTOMERIO_WRITER_ID] == config.customerio_token
        assert ctx.writer_tokens[demo5.VERDICT_RELAY_WRITER_ID] == config.verdict_relay_token
        assert ctx.writer_tokens[demo5.REBUILD_WRITER_ID] == config.projection_replay_token
        assert ctx.board_transport is None
        assert ctx.board_base_url == config.twenty_target.url
        assert ctx.board_token == config.twenty_target.token
        assert ctx.board_store is None
        assert ctx.patient_key == ctx.fixtures["consent_export_row"]["subject_key"]
        assert ctx.pool.waited is True
    finally:
        ctx.close()
    assert ctx.pool.closed is True


def test_build_live_context_warehouse_reader_reads_stg_events_through_the_fake_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = demo5.resolve_live_config(_LIVE_ENV)
    connection = _FakeSnowflakeConnection([_stg_events_row()])
    monkeypatch.setattr(demo5, "_snowflake_connect_stg_events", lambda _config: connection)
    ctx = demo5.build_live_context(config, pool_factory=_FakePool)
    try:
        result = ctx.warehouse_reader(frozenset({("enrollment", "pt-0001")}))
        assert result[("enrollment", "pt-0001")][0]["event_id"] == "evt-1"
    finally:
        ctx.close()
