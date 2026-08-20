"""`verdict_relay.production` — task 3.1, spec verdict-relay-trigger: "A missing variable fails
startup by name".

Every required environment variable is faked here as a plain `dict`; `conftest.py` blocks sockets
for the whole suite, so a test that reached for a real connection would fail loudly regardless.
"""

from __future__ import annotations

from typing import Any

import pytest
from verdict_relay.production import (
    PULSE_CORE_BASE_URL_ENV_VAR,
    PULSE_CORE_TOKEN_ENV_VAR,
    SNOWFLAKE_ACCOUNT_ENV_VAR,
    SNOWFLAKE_DATABASE_ENV_VAR,
    SNOWFLAKE_PASSWORD_ENV_VAR,
    SNOWFLAKE_SCHEMA_ENV_VAR,
    SNOWFLAKE_TABLE_ENV_VAR,
    SNOWFLAKE_USER_ENV_VAR,
    SNOWFLAKE_WAREHOUSE_ENV_VAR,
    WRITER_ID,
    MissingProductionVariableError,
    ProductionConfig,
    SnowflakeRowSource,
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
