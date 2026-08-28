"""Production wiring (task 3.1, spec verdict-relay-trigger): resolves the relay's Snowflake
`RowSource`, `LedgerCursorStore`, and command-API `PulseCoreClient` from configuration and the
environment — the S1.3 deferral `run.py`'s module docstring names.

`resolve_production_config` reads every required environment variable before any connection is
attempted, in a fixed order, so a single missing variable fails startup naming exactly that
variable (spec: "A missing variable fails startup by name") rather than surfacing later as a
Snowflake or ledger connection error. Only variable *names* are pinned here (D15); values live in
the deploy environment and are never logged.

The Snowflake driver is imported lazily inside `_snowflake_connect`, the only place it is ever
imported — mirrors `pulse_core.catalog_release_cli._snowflake_connect` — so importing this module,
constructing a `SnowflakeRowSource` with a fake `connect`, or running any test against
`FixtureRowSource` never requires the driver installed.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from os import environ
from typing import Any

from pulse_core.client import PulseCoreClient

from verdict_relay.mart_reader import CONTRACT_COLUMNS, LedgerCursorStore

#: This relay's own D15 writer identity — the credential the ledger resolves as `verdict-relay`
#: (ADR-0003: attribution is authentication). A design-time constant, not configuration: every
#: deploy of this relay is this one writer, matching the identity `declarer.py`'s tests already
#: assume (`writer_id="verdict-relay"`).
WRITER_ID = "verdict-relay"

#: Env var names (values live in the deploy environment; never hardcoded, never logged — D15
#: mirrors the monorepo convention `relay_worker.py` / `warehouse_smoke.py` / `schedules.cli`
#: already follow).
PULSE_CORE_BASE_URL_ENV_VAR = "VERDICT_RELAY_PULSE_CORE_BASE_URL"
PULSE_CORE_TOKEN_ENV_VAR = "VERDICT_RELAY_TOKEN"  # noqa: S105 — an env var name, not a secret
SNOWFLAKE_ACCOUNT_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_ACCOUNT"
SNOWFLAKE_USER_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_USER"
SNOWFLAKE_PASSWORD_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_PASSWORD"  # noqa: S105
SNOWFLAKE_WAREHOUSE_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_WAREHOUSE"
SNOWFLAKE_DATABASE_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_DATABASE"
SNOWFLAKE_SCHEMA_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_SCHEMA"
SNOWFLAKE_TABLE_ENV_VAR = "VERDICT_RELAY_SNOWFLAKE_TABLE"

#: Read in exactly this order — the first missing variable is the one startup names (spec: "A
#: missing variable fails startup by name"), so this order is what a misconfigured deploy sees.
_REQUIRED_ENV_VARS: tuple[str, ...] = (
    PULSE_CORE_BASE_URL_ENV_VAR,
    PULSE_CORE_TOKEN_ENV_VAR,
    SNOWFLAKE_ACCOUNT_ENV_VAR,
    SNOWFLAKE_USER_ENV_VAR,
    SNOWFLAKE_PASSWORD_ENV_VAR,
    SNOWFLAKE_WAREHOUSE_ENV_VAR,
    SNOWFLAKE_DATABASE_ENV_VAR,
    SNOWFLAKE_SCHEMA_ENV_VAR,
    SNOWFLAKE_TABLE_ENV_VAR,
)


class MissingProductionVariableError(RuntimeError):
    """A required environment variable is unset; startup fails naming it, never its value."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"required environment variable {name} is not set")


@dataclass(frozen=True)
class ProductionConfig:
    """Every production dependency's configuration, resolved from the environment once."""

    pulse_core_base_url: str
    pulse_core_token: str
    snowflake_account: str
    snowflake_user: str
    snowflake_password: str
    snowflake_warehouse: str
    snowflake_database: str
    snowflake_schema: str
    snowflake_table: str


def resolve_production_config(env: Mapping[str, str] | None = None) -> ProductionConfig:
    """Read every required variable, failing on the first missing one, before any connection.

    `env` defaults to `os.environ`; tests pass a plain `dict` so the check never touches the real
    process environment.
    """
    source = environ if env is None else env
    values: dict[str, str] = {}
    for name in _REQUIRED_ENV_VARS:
        value = source.get(name)
        if value is None:
            raise MissingProductionVariableError(name)
        values[name] = value

    return ProductionConfig(
        pulse_core_base_url=values[PULSE_CORE_BASE_URL_ENV_VAR],
        pulse_core_token=values[PULSE_CORE_TOKEN_ENV_VAR],
        snowflake_account=values[SNOWFLAKE_ACCOUNT_ENV_VAR],
        snowflake_user=values[SNOWFLAKE_USER_ENV_VAR],
        snowflake_password=values[SNOWFLAKE_PASSWORD_ENV_VAR],
        snowflake_warehouse=values[SNOWFLAKE_WAREHOUSE_ENV_VAR],
        snowflake_database=values[SNOWFLAKE_DATABASE_ENV_VAR],
        snowflake_schema=values[SNOWFLAKE_SCHEMA_ENV_VAR],
        snowflake_table=values[SNOWFLAKE_TABLE_ENV_VAR],
    )


def _snowflake_connect(config: ProductionConfig) -> Any:
    """The only place `snowflake.connector` is ever imported (mirrors
    `pulse_core.catalog_release_cli._snowflake_connect`'s own lazy-import posture)."""
    connector = importlib.import_module("snowflake.connector")
    return connector.connect(
        account=config.snowflake_account,
        user=config.snowflake_user,
        password=config.snowflake_password,
        warehouse=config.snowflake_warehouse,
        database=config.snowflake_database,
        schema=config.snowflake_schema,
    )


class SnowflakeRowSource:
    """The production `RowSource`: pages `CONTRACT_COLUMNS` off one Snowflake mart table.

    Constructed from `ProductionConfig`; the driver connects lazily on first `fetch` through
    `connect` (defaulting to `_snowflake_connect`), so a test can construct and even page this
    class against a fake `connect` without the driver installed — the same seam
    `pulse_core.catalog_release_cli.main` uses for its own `connect` factory.
    """

    def __init__(
        self,
        config: ProductionConfig,
        *,
        connect: Callable[[ProductionConfig], Any] | None = None,
    ) -> None:
        self._config = config
        self._connect = connect or _snowflake_connect
        self._connection: Any | None = None

    def _ensure_connection(self) -> Any:
        if self._connection is None:
            self._connection = self._connect(self._config)
        return self._connection

    def fetch(self, *, after: str | None, limit: int) -> Sequence[Mapping[str, object]]:
        connection = self._ensure_connection()
        columns = ", ".join(CONTRACT_COLUMNS)
        table = self._config.snowflake_table
        cursor = connection.cursor()
        try:
            if after is None:
                cursor.execute(
                    f"SELECT {columns} FROM {table} ORDER BY computed_at ASC LIMIT %s",  # noqa: S608
                    (limit,),
                )
            else:
                cursor.execute(
                    f"SELECT {columns} FROM {table} "  # noqa: S608
                    "WHERE computed_at > %s ORDER BY computed_at ASC LIMIT %s",
                    (after, limit),
                )
            rows = [dict(zip(CONTRACT_COLUMNS, row, strict=True)) for row in cursor.fetchall()]
            if len(rows) < limit:
                return rows
            # A full page may cut mid-tie, and the reader advances its cursor with a strict
            # `computed_at > boundary` — any tied row beyond the cut would be skipped forever.
            # The RowSource protocol therefore requires the tie never split: re-fetch every row
            # sharing the boundary `computed_at` and splice them in (`FixtureRowSource` over-fills
            # the same way).
            boundary = rows[-1]["computed_at"]
            head = [row for row in rows if row["computed_at"] != boundary]
            cursor.execute(
                f"SELECT {columns} FROM {table} WHERE computed_at = %s",  # noqa: S608
                (boundary,),
            )
            ties = [dict(zip(CONTRACT_COLUMNS, row, strict=True)) for row in cursor.fetchall()]
            return [*head, *ties]
        finally:
            cursor.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def build_production_dependencies(
    config: ProductionConfig,
) -> tuple[SnowflakeRowSource, LedgerCursorStore, PulseCoreClient]:
    """Construct the relay's three production dependencies from already-resolved configuration.

    Performs no environment reads of its own — call `resolve_production_config` first, so every
    required variable has already been validated present before any connection is opened.
    """
    row_source = SnowflakeRowSource(config)
    cursor_store = LedgerCursorStore(
        config.pulse_core_base_url,
        writer_id=WRITER_ID,
        token=config.pulse_core_token,
    )
    # max_attempts=1: retry policy belongs to the `Declarer` (declarer.py design decision 4); a
    # client that also retried would multiply the attempt budget, exactly what `service_client`
    # already pins for the same reason.
    client = PulseCoreClient(
        config.pulse_core_base_url,
        writer_id=WRITER_ID,
        token=config.pulse_core_token,
        max_attempts=1,
    )
    return row_source, cursor_store, client
