"""The deploy entrypoint's credential posture (catalog-authority 4.3).

Covers the `catalog-release` spec scenarios "Planning without credentials" and "Apply without
credentials is an error". Everything here is offline: the plan run touches only the repo's
released snapshots, apply runs against a fake `ReleaseConnection`, and the real snowflake
driver is never imported — a stub module stands in for it where the adapter is under test.
"""

from __future__ import annotations

import sys
import types

import pytest
from pulse_core import catalog_release_cli
from pulse_core.catalog_release import snapshot_checksum
from pulse_core.catalog_release_cli import REQUIRED_CREDENTIALS, build_release, main
from pulse_core.catalog_snapshots import MANIFEST_NAME, RELEASES_DIR, read_manifest

RELEASED_VERSION = read_manifest(RELEASES_DIR / MANIFEST_NAME)[-1].version

CREDENTIALS = {
    "SNOWFLAKE_ACCOUNT": "acme-test",
    "SNOWFLAKE_USER": "release-bot",
    "SNOWFLAKE_PASSWORD": "hunter2",
}

GIT_ENV = {"GITHUB_SHA": "f" * 40, "GITHUB_REF": "refs/heads/main"}


class FakeConnection:
    """The thin boundary, faked: records statements, answers the guard from `released`."""

    def __init__(self, released: dict[str, str] | None = None) -> None:
        self.released = dict(released or {})
        self.executed: list[str] = []

    def execute(self, statement: str) -> list[tuple[object, ...]]:
        self.executed.append(statement)
        if statement.lstrip().startswith("SELECT"):
            return [(checksum,) for version, checksum in self.released.items() if f"'{version}'" in statement]
        return []


def forbidden_connect(env: dict[str, str]) -> FakeConnection:
    msg = "a plan-only run must never open a warehouse connection"
    raise AssertionError(msg)


class TestPlanningWithoutCredentials:
    """Spec: Planning without credentials — print the plan, exit zero, no connection."""

    def test_plan_prints_rendered_release_and_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main([], env=GIT_ENV, connect=forbidden_connect)
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "INSERT INTO PULSE_CATALOG_PLACEHOLDER.CATALOG.VERSIONS" in out
        assert f"'{RELEASED_VERSION}'" in out

    def test_plan_is_insert_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        main([], env=GIT_ENV, connect=forbidden_connect)
        out = capsys.readouterr().out
        for forbidden in ("UPDATE ", "DELETE ", "MERGE ", "TRUNCATE "):
            assert forbidden not in out

    def test_plan_with_credentials_still_only_plans(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Credentials alone never mean apply — only an explicit --apply does."""
        exit_code = main([], env={**CREDENTIALS, **GIT_ENV}, connect=forbidden_connect)
        assert exit_code == 0
        assert "INSERT INTO" in capsys.readouterr().out

    def test_plan_carries_the_git_identity_from_the_actions_env(self, capsys: pytest.CaptureFixture[str]) -> None:
        main([], env=GIT_ENV, connect=forbidden_connect)
        out = capsys.readouterr().out
        assert "f" * 40 in out
        assert "refs/heads/main" in out

    def test_plan_falls_back_to_local_git_identity(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Outside Actions (no GITHUB_SHA/GITHUB_REF) the local git commit stamps the plan."""
        exit_code = main([], env={}, connect=forbidden_connect)
        assert exit_code == 0
        assert "INSERT INTO" in capsys.readouterr().out


class TestApplyWithoutCredentialsIsAnError:
    """Spec: Apply without credentials is an error — nonzero, naming what is missing."""

    def test_apply_without_any_credential_fails_naming_them_all(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--apply"], env=GIT_ENV, connect=forbidden_connect)
        err = capsys.readouterr().err
        assert exit_code != 0
        for name in REQUIRED_CREDENTIALS:
            assert name in err

    def test_apply_names_only_the_missing_credentials(self, capsys: pytest.CaptureFixture[str]) -> None:
        partial = {**GIT_ENV, "SNOWFLAKE_ACCOUNT": "acme-test"}
        exit_code = main(["--apply"], env=partial, connect=forbidden_connect)
        err = capsys.readouterr().err
        assert exit_code != 0
        assert "SNOWFLAKE_ACCOUNT" not in err
        assert "SNOWFLAKE_USER" in err
        assert "SNOWFLAKE_PASSWORD" in err

    def test_an_empty_credential_counts_as_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An empty secret (the unset-secret shape in Actions) is missing, not present."""
        env = {**CREDENTIALS, **GIT_ENV, "SNOWFLAKE_PASSWORD": ""}
        exit_code = main(["--apply"], env=env, connect=forbidden_connect)
        assert exit_code != 0
        assert "SNOWFLAKE_PASSWORD" in capsys.readouterr().err

    def test_apply_without_credentials_writes_nothing(self) -> None:
        connection = FakeConnection()
        exit_code = main(["--apply"], env=GIT_ENV, connect=lambda env: connection)
        assert exit_code != 0
        assert connection.executed == []


class TestApplyWithCredentials:
    """`APPLY=1` with credentials executes through the injected connection."""

    def test_fresh_version_applies(self, capsys: pytest.CaptureFixture[str]) -> None:
        connection = FakeConnection()
        exit_code = main(["--apply"], env={**CREDENTIALS, **GIT_ENV}, connect=lambda env: connection)
        out = capsys.readouterr().out
        assert exit_code == 0
        assert any(statement.startswith("INSERT INTO") for statement in connection.executed)
        assert RELEASED_VERSION in out
        assert "applied" in out

    def test_identical_rerelease_is_a_noop(self, capsys: pytest.CaptureFixture[str]) -> None:
        released = {RELEASED_VERSION: snapshot_checksum(RELEASED_VERSION)}
        connection = FakeConnection(released=released)
        exit_code = main(["--apply"], env={**CREDENTIALS, **GIT_ENV}, connect=lambda env: connection)
        out = capsys.readouterr().out
        assert exit_code == 0
        assert not any(statement.startswith("INSERT") for statement in connection.executed)
        assert "already_released" in out

    def test_database_env_overrides_the_placeholder(self, capsys: pytest.CaptureFixture[str]) -> None:
        env = {**CREDENTIALS, **GIT_ENV, "SNOWFLAKE_DATABASE": "PULSE_PROD"}
        connection = FakeConnection()
        exit_code = main(["--apply"], env=env, connect=lambda env: connection)
        assert exit_code == 0
        assert all("PULSE_CATALOG_PLACEHOLDER" not in statement for statement in connection.executed)
        assert any("PULSE_PROD.CATALOG" in statement for statement in connection.executed)


class TestBuildRelease:
    def test_release_is_the_newest_manifest_version_with_its_checksum(self) -> None:
        catalog, source, _config = build_release(env=GIT_ENV)
        assert catalog.catalog_version == RELEASED_VERSION
        assert source.snapshot_checksum == snapshot_checksum(RELEASED_VERSION)


class TestSnowflakeAdapter:
    """The default connect factory adapts the driver to `ReleaseConnection` — via a stub."""

    def test_connect_builds_a_connection_that_executes_through_a_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        executed: list[str] = []

        class StubCursor:
            def execute(self, statement: str) -> None:
                executed.append(statement)

            def fetchall(self) -> list[tuple[object, ...]]:
                return [("row",)]

        class StubDriverConnection:
            def cursor(self) -> StubCursor:
                return StubCursor()

        connect_kwargs: dict[str, object] = {}

        def stub_connect(**kwargs: object) -> StubDriverConnection:
            connect_kwargs.update(kwargs)
            return StubDriverConnection()

        stub = types.ModuleType("snowflake.connector")
        stub.connect = stub_connect  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "snowflake.connector", stub)

        connection = catalog_release_cli._snowflake_connect({**CREDENTIALS, "SNOWFLAKE_DATABASE": "PULSE_PROD"})
        rows = connection.execute("SELECT 1;")

        assert rows == [("row",)]
        assert executed == ["SELECT 1;"]
        assert connect_kwargs["account"] == "acme-test"
        assert connect_kwargs["user"] == "release-bot"
        assert connect_kwargs["database"] == "PULSE_PROD"
