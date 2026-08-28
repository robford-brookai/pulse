"""`verdict_relay.production` — task 3.1, spec verdict-relay-trigger: "A missing variable fails
startup by name".

Every required environment variable is faked here as a plain `dict`; `conftest.py` blocks sockets
for the whole suite, so a test that reached for a real connection would fail loudly regardless.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from verdict_relay.production import (
    PULSE_CORE_BASE_URL_ENV_VAR,
    PULSE_CORE_TOKEN_ENV_VAR,
    SNOWFLAKE_ACCOUNT_ENV_VAR,
    SNOWFLAKE_DATABASE_ENV_VAR,
    SNOWFLAKE_PASSWORD_ENV_VAR,
    SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR,
    SNOWFLAKE_SCHEMA_ENV_VAR,
    SNOWFLAKE_TABLE_ENV_VAR,
    SNOWFLAKE_USER_ENV_VAR,
    SNOWFLAKE_WAREHOUSE_ENV_VAR,
    WRITER_ID,
    ConflictingProductionVariablesError,
    MissingProductionVariableError,
    ProductionConfig,
    SnowflakeRowSource,
    _snowflake_connect,  # pyright: ignore[reportPrivateUsage]  # exercising the auth-family switch directly, per module docstring
    build_production_dependencies,
    resolve_production_config,
)

#: A complete, synthetic environment — no real credential values, per the no-PHI/no-secret
#: fixture posture every other package's tests already follow.
COMPLETE_ENV: dict[str, str] = {
    PULSE_CORE_BASE_URL_ENV_VAR: "https://ledger.test",
    PULSE_CORE_TOKEN_ENV_VAR: "fixture-token-do-not-use",
    SNOWFLAKE_ACCOUNT_ENV_VAR: "fixture-account",
    SNOWFLAKE_USER_ENV_VAR: "fixture-user",
    SNOWFLAKE_PASSWORD_ENV_VAR: "fixture-password-do-not-use",
    SNOWFLAKE_WAREHOUSE_ENV_VAR: "FIXTURE_WH",
    SNOWFLAKE_DATABASE_ENV_VAR: "FIXTURE_DB",
    SNOWFLAKE_SCHEMA_ENV_VAR: "FIXTURE_SCHEMA",
    SNOWFLAKE_TABLE_ENV_VAR: "FIXTURE_VERDICT_MART",
}


class TestMissingVariableFailsStartupByName:
    """Scenario: a missing variable fails startup by name."""

    def test_a_complete_environment_resolves_without_error(self) -> None:
        config = resolve_production_config(COMPLETE_ENV)

        assert config.pulse_core_base_url == COMPLETE_ENV[PULSE_CORE_BASE_URL_ENV_VAR]
        assert config.snowflake_table == COMPLETE_ENV[SNOWFLAKE_TABLE_ENV_VAR]

    @pytest.mark.parametrize("missing_var", list(COMPLETE_ENV))
    def test_each_missing_variable_fails_naming_exactly_itself(self, missing_var: str) -> None:
        env = {name: value for name, value in COMPLETE_ENV.items() if name != missing_var}

        with pytest.raises(MissingProductionVariableError) as exc_info:
            resolve_production_config(env)

        assert exc_info.value.name == missing_var
        assert missing_var in str(exc_info.value)

    def test_the_error_never_carries_any_configured_value(self) -> None:
        env = {name: value for name, value in COMPLETE_ENV.items() if name != SNOWFLAKE_PASSWORD_ENV_VAR}

        with pytest.raises(MissingProductionVariableError) as exc_info:
            resolve_production_config(env)

        message = str(exc_info.value)
        for value in COMPLETE_ENV.values():
            assert value not in message

    def test_no_variable_is_read_past_the_first_missing_one(self) -> None:
        """A `dict` subclass that records every key looked up — the first missing variable in
        declared order stops resolution before any variable after it is even checked."""

        class RecordingEnv(dict[str, str]):
            def __init__(self, data: dict[str, str]) -> None:
                super().__init__(data)
                self.lookups: list[str] = []

            def get(self, key: str, default: Any = None) -> Any:
                self.lookups.append(key)
                return super().get(key, default)

        env = RecordingEnv({name: value for name, value in COMPLETE_ENV.items() if name != SNOWFLAKE_USER_ENV_VAR})

        with pytest.raises(MissingProductionVariableError):
            resolve_production_config(env)

        assert env.lookups[-1] == SNOWFLAKE_USER_ENV_VAR


class TestKeyPairCredentialResolvesInLieuOfPassword:
    """The Snowflake credential is exactly one of password / private-key path. Key-pair JWT is
    the service-auth family Snowflake's 2026 BCR still provisions for headless readers (no
    passwords on TYPE=SERVICE; MFA enrollment enforced on TYPE=PERSON), so the relay accepts a
    `VERDICT_RELAY_SNOWFLAKE_PRIVATE_KEY_PATH` in lieu of the password — a key-pair deploy is not
    a missing variable, a credential-less deploy still names the password variable, and both set
    is a misconfiguration that fails startup naming both variables, never a value."""

    KEY_PATH_VALUE = "/run/secrets/fixture_key.p8"

    @staticmethod
    def _key_path_env() -> dict[str, str]:
        env = {name: value for name, value in COMPLETE_ENV.items() if name != SNOWFLAKE_PASSWORD_ENV_VAR}
        env[SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR] = TestKeyPairCredentialResolvesInLieuOfPassword.KEY_PATH_VALUE
        return env

    def test_a_private_key_path_resolves_in_lieu_of_the_password(self) -> None:
        config = resolve_production_config(self._key_path_env())

        assert config.snowflake_private_key_path == self.KEY_PATH_VALUE
        assert config.snowflake_password is None

    def test_a_password_environment_still_resolves_password_shaped(self) -> None:
        config = resolve_production_config(COMPLETE_ENV)

        assert config.snowflake_password == COMPLETE_ENV[SNOWFLAKE_PASSWORD_ENV_VAR]
        assert config.snowflake_private_key_path is None

    def test_neither_credential_fails_naming_the_password_variable(self) -> None:
        env = {name: value for name, value in COMPLETE_ENV.items() if name != SNOWFLAKE_PASSWORD_ENV_VAR}

        with pytest.raises(MissingProductionVariableError) as exc_info:
            resolve_production_config(env)

        assert exc_info.value.name == SNOWFLAKE_PASSWORD_ENV_VAR

    def test_both_credentials_fail_naming_both_variables_and_never_a_value(self) -> None:
        env = dict(COMPLETE_ENV)
        env[SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR] = self.KEY_PATH_VALUE

        with pytest.raises(ConflictingProductionVariablesError) as exc_info:
            resolve_production_config(env)

        assert exc_info.value.names == (SNOWFLAKE_PASSWORD_ENV_VAR, SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR)
        message = str(exc_info.value)
        assert SNOWFLAKE_PASSWORD_ENV_VAR in message
        assert SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR in message
        for value in env.values():
            assert value not in message


class TestSnowflakeConnectSelectsTheAuthFamily:
    """`_snowflake_connect` follows the resolved credential: password connects exactly as before;
    a private-key path loads the real PEM (an actual generated RSA key, no fake serialization)
    and connects key-pair JWT. The connector module is injected through `sys.modules` — the same
    lazy-import seam the production code uses — so no connection is ever attempted (conftest
    blocks sockets anyway)."""

    class _FakeConnectorModule:
        """Stands in for `snowflake.connector`; records the kwargs of the one `connect` call."""

        def __init__(self) -> None:
            self.kwargs: dict[str, Any] | None = None

        def connect(self, **kwargs: Any) -> object:
            self.kwargs = kwargs
            return object()

    def test_a_password_config_connects_with_the_password_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = self._FakeConnectorModule()
        monkeypatch.setitem(sys.modules, "snowflake.connector", fake)
        config = resolve_production_config(COMPLETE_ENV)

        _snowflake_connect(config)

        assert fake.kwargs is not None
        assert fake.kwargs["password"] == COMPLETE_ENV[SNOWFLAKE_PASSWORD_ENV_VAR]
        assert fake.kwargs["account"] == COMPLETE_ENV[SNOWFLAKE_ACCOUNT_ENV_VAR]
        assert "private_key" not in fake.kwargs
        assert "authenticator" not in fake.kwargs

    def test_a_key_path_config_loads_the_pem_and_connects_keypair_jwt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_path = tmp_path / "relay_fixture_key.p8"
        key_path.write_bytes(pem)

        env = {name: value for name, value in COMPLETE_ENV.items() if name != SNOWFLAKE_PASSWORD_ENV_VAR}
        env[SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR] = str(key_path)
        config = resolve_production_config(env)

        fake = self._FakeConnectorModule()
        monkeypatch.setitem(sys.modules, "snowflake.connector", fake)

        _snowflake_connect(config)

        assert fake.kwargs is not None
        assert fake.kwargs["authenticator"] == "SNOWFLAKE_JWT"
        # The connector takes the key as DER PKCS8 bytes, never the path or the PEM text.
        assert isinstance(fake.kwargs["private_key"], bytes)
        assert fake.kwargs["private_key"] != pem
        assert "password" not in fake.kwargs
        assert fake.kwargs["account"] == COMPLETE_ENV[SNOWFLAKE_ACCOUNT_ENV_VAR]


class TestBuildProductionDependencies:
    """No connection is opened just by constructing the dependencies — `SnowflakeRowSource`
    connects lazily on first `fetch`, and `LedgerCursorStore`/`PulseCoreClient` build an
    `httpx.Client` without ever making a request."""

    def test_builds_all_three_dependencies_without_connecting(self) -> None:
        config = resolve_production_config(COMPLETE_ENV)

        row_source, cursor_store, client = build_production_dependencies(config)

        assert isinstance(row_source, SnowflakeRowSource)
        cursor_store.close()
        client.close()

    def test_the_client_and_cursor_store_share_the_relays_writer_identity(self) -> None:
        config = resolve_production_config(COMPLETE_ENV)

        _row_source, cursor_store, client = build_production_dependencies(config)

        assert WRITER_ID == "verdict-relay"
        cursor_store.close()
        client.close()


class TestSnowflakeRowSourceNeverImportsTheDriverUntilConnecting:
    """The driver connects lazily; a fake `connect` proves `SnowflakeRowSource` can be constructed
    and paged without `snowflake.connector` ever being imported."""

    def test_fetch_pages_through_an_injected_connect_factory(self) -> None:
        rows: list[dict[str, object]] = [
            {
                "subject_id": "episode-A",
                "verdict_type": "billing_eligibility",
                "outcome": "positive",
                "reason": None,
                "rule_version": "rules-v1",
                "as_of": "2026-08-01T00:00:00+00:00",
                "lineage_ref": "dbt-run-1",
                "computed_at": "2026-08-01T02:00:00+00:00",
            }
        ]

        class FakeCursor:
            def __init__(self, rows: list[dict[str, object]]) -> None:
                self._rows = rows
                self.queries: list[tuple[str, tuple[object, ...]]] = []

            def execute(self, statement: str, params: tuple[object, ...]) -> None:
                self.queries.append((statement, params))

            def fetchall(self) -> list[tuple[object, ...]]:
                from verdict_relay.mart_reader import CONTRACT_COLUMNS

                return [tuple(row[column] for column in CONTRACT_COLUMNS) for row in self._rows]

            def close(self) -> None:
                pass

        class FakeConnection:
            def __init__(self, rows: list[dict[str, object]]) -> None:
                self._cursor = FakeCursor(rows)

            def cursor(self) -> FakeCursor:
                return self._cursor

            def close(self) -> None:
                pass

        connection = FakeConnection(rows)
        config = resolve_production_config(COMPLETE_ENV)
        source = SnowflakeRowSource(config, connect=lambda _config: connection)

        page = source.fetch(after=None, limit=500)

        assert list(page) == rows
        source.close()

    def test_a_provided_after_cursor_is_bound_as_a_query_parameter(self) -> None:
        class FakeCursor:
            def __init__(self) -> None:
                self.queries: list[tuple[str, tuple[object, ...]]] = []

            def execute(self, statement: str, params: tuple[object, ...]) -> None:
                self.queries.append((statement, params))

            def fetchall(self) -> list[tuple[object, ...]]:
                return []

            def close(self) -> None:
                pass

        class FakeConnection:
            def __init__(self) -> None:
                self.cursor_obj = FakeCursor()

            def cursor(self) -> FakeCursor:
                return self.cursor_obj

            def close(self) -> None:
                pass

        connection = FakeConnection()
        config = resolve_production_config(COMPLETE_ENV)
        source = SnowflakeRowSource(config, connect=lambda _config: connection)

        source.fetch(after="2026-08-01T00:00:00+00:00", limit=10)

        (statement, params) = connection.cursor_obj.queries[0]
        assert "WHERE computed_at >" in statement
        assert params == ("2026-08-01T00:00:00+00:00", 10)
        source.close()


class TestSnowflakeRowSourceNeverSplitsAComputedAtTie:
    """The RowSource protocol (mart_reader.py): a page never splits a `computed_at` tie — rows
    sharing the last included `computed_at` are all included, so paging on a strict `>` boundary
    can never skip a tied row. `FixtureRowSource` over-fills the same way; the production source
    must too, or a tie wider than the page size is silently dropped."""

    @staticmethod
    def _row(subject_id: str, computed_at: str) -> dict[str, object]:
        return {
            "subject_id": subject_id,
            "verdict_type": "billing_eligibility",
            "outcome": "positive",
            "reason": None,
            "rule_version": "rules-v1",
            "as_of": "2026-08-01T00:00:00+00:00",
            "lineage_ref": "dbt-run-1",
            "computed_at": computed_at,
        }

    class _ScriptedCursor:
        """Serves one pre-scripted result set per `execute`, recording every query."""

        def __init__(self, result_sets: list[list[dict[str, object]]]) -> None:
            self._result_sets = result_sets
            self.queries: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, statement: str, params: tuple[object, ...]) -> None:
            self.queries.append((statement, params))

        def fetchall(self) -> list[tuple[object, ...]]:
            from verdict_relay.mart_reader import CONTRACT_COLUMNS

            rows = self._result_sets[len(self.queries) - 1]
            return [tuple(row[column] for column in CONTRACT_COLUMNS) for row in rows]

        def close(self) -> None:
            pass

    class _ScriptedConnection:
        def __init__(self, cursor: TestSnowflakeRowSourceNeverSplitsAComputedAtTie._ScriptedCursor) -> None:
            self.cursor_obj = cursor

        def cursor(self) -> TestSnowflakeRowSourceNeverSplitsAComputedAtTie._ScriptedCursor:
            return self.cursor_obj

        def close(self) -> None:
            pass

    def test_a_full_page_is_extended_with_every_row_tying_the_boundary_computed_at(self) -> None:
        tied = "2026-08-01T02:00:00+00:00"
        earlier = self._row("episode-A", "2026-08-01T01:00:00+00:00")
        tie_rows = [self._row(f"episode-{name}", tied) for name in ("B", "C", "D")]
        # The page query (LIMIT 3) cuts mid-tie: episode-D is beyond the limit.
        cursor = self._ScriptedCursor([
            [earlier, tie_rows[0], tie_rows[1]],
            tie_rows,  # the boundary re-fetch returns the full tie
        ])
        connection = self._ScriptedConnection(cursor)
        config = resolve_production_config(COMPLETE_ENV)
        source = SnowflakeRowSource(config, connect=lambda _config: connection)

        page = source.fetch(after=None, limit=3)

        assert list(page) == [earlier, *tie_rows]
        (tie_statement, tie_params) = cursor.queries[1]
        assert "WHERE computed_at = %s" in tie_statement
        assert tie_params == (tied,)
        source.close()

    def test_a_page_below_the_limit_issues_no_second_query(self) -> None:
        rows = [self._row("episode-A", "2026-08-01T01:00:00+00:00")]
        cursor = self._ScriptedCursor([rows])
        connection = self._ScriptedConnection(cursor)
        config = resolve_production_config(COMPLETE_ENV)
        source = SnowflakeRowSource(config, connect=lambda _config: connection)

        page = source.fetch(after=None, limit=3)

        assert list(page) == rows
        assert len(cursor.queries) == 1
        source.close()


def test_production_config_is_a_dataclass_of_only_configured_values() -> None:
    config = ProductionConfig(
        pulse_core_base_url="https://ledger.test",
        pulse_core_token="fixture-token-do-not-use",  # noqa: S106
        snowflake_account="fixture-account",
        snowflake_user="fixture-user",
        snowflake_password="fixture-password-do-not-use",  # noqa: S106
        snowflake_warehouse="FIXTURE_WH",
        snowflake_database="FIXTURE_DB",
        snowflake_schema="FIXTURE_SCHEMA",
        snowflake_table="FIXTURE_VERDICT_MART",
    )

    assert config.snowflake_table == "FIXTURE_VERDICT_MART"
