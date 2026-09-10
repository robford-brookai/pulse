"""Production wiring for a ledger family's sweep (task 3.4, design.md decision 11).

Task 3.2 registered the three consumers and their readers; nothing called `build_consumers`, so
`cli.py`'s ledger-family path kept wave 1's empty tuple and every real run reported `no_consumers`.
This module is the missing half: it resolves the environment each consumer's source needs, builds
the production readers over those sources, and runs one family's comparison across whichever of
them this environment actually has.

Three credential postures meet in one process, and each keeps its own:

- **`twenty-board`** — `BoardReader` over the projection's own read client
  (`ProjectionRestClient`), addressed by the `PULSE_TWENTY_<TARGET>_URL` / `_TOKEN` pair every
  credentialed Twenty target already uses (`pulse_core.twenty_deploy.resolve_target`), with the
  target itself named by `SCHEDULES_TWENTY_TARGET`.
- **`warehouse-landing`** — `LandingReader` over a read-only Snowflake `FamilyRowSource` on the
  published fold view (`STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE`, task 1.2). The view is fully
  qualified by contract, so only the connection is configuration: account, user, warehouse, and
  exactly one credential — a password, or the key-pair PEM path Snowflake's 2026 BCR requires of a
  headless service reader (`verdict_relay.production` carries the same either/or for the same
  reason).
- **`graph-projection-patients`** — `PatientsReader` over a read-only Postgres `FamilyRowSource` on
  the OCEAN graph database (`SCHEDULES_GRAPH_DATABASE_URL`), the `patients` projection
  `m1-retire-patient-state` writes.

The snapshot is `LedgerStateReader` on a `PulseCoreClient`, per subject, over the union of subject
keys the consumers returned — the command API exposes no bulk enumeration, and the sweep holds no
ledger connection of its own (design.md decision 2).

**Missing versus unconfigured.** A source group is *unconfigured* when it is absent entirely: the
consumer is skipped, named `unconfigured` in the receipt, and the rest of the run proceeds — which
is what lets the `enrollment` sweep run on dev01, where no OCEAN graph database exists (design.md
decision 11). A group that is *partly* set is a deploy fault, not an absence, and fails startup
naming the first missing variable, before any connection is opened (spec: "A missing variable fails
startup by name"). The ledger's own pair is required outright: without it there is no snapshot and
so no sweep at all.

**Read-only, all the way down.** Every reader here exposes `read_family` / `read_subject` and
nothing else; the Snowflake source issues one parameterized `SELECT` against the fold view, and the
Postgres session is set `read_only` before its first statement. No writer credential, no write verb
(design.md decision 2).

Only variable *names* are pinned in this module; values live in the deploy environment and are
never logged. Nothing here reaches a payload value: rows carry a subject key, a catalog state name,
and a sequence.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from os import environ
from pathlib import Path
from typing import Any

from pulse_core.catalog_gen import load_catalog
from pulse_core.client import PulseCoreClient
from pulse_core.twenty_deploy import DeployError, env_var_names, resolve_target
from pulse_core.twenty_model import encode_option_value
from twenty_projection.apply import BoardTarget, ProjectionRestClient

from schedules.consumer_registry import BOARD_TARGETS, build_consumers
from schedules.projection_conformance import (
    MIN_COMPLETE_FROM,
    ConsumerConformance,
    FamilyConformance,
    SubjectSnapshot,
    compare_family,
    conform_family,
    report_uncitable_consumer,
    report_unconfigured_consumer,
    snapshot_from_read,
)
from schedules.sweep_readers import (
    BoardFields,
    BoardReader,
    FamilyRead,
    LandingReader,
    LedgerStateReader,
    PatientsReader,
    SweptRow,
)
from schedules.sweep_registry import Consumer, Family

__all__ = [
    "BOARD_SUBJECT_KEY_FIELD",
    "FOLD_VIEW",
    "GRAPH_DATABASE_URL_ENV_VAR",
    "PULSE_CORE_BASE_URL_ENV_VAR",
    "SNOWFLAKE_ACCOUNT_ENV_VAR",
    "SNOWFLAKE_PASSWORD_ENV_VAR",
    "SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR",
    "SNOWFLAKE_USER_ENV_VAR",
    "SNOWFLAKE_WAREHOUSE_ENV_VAR",
    "SWEEP_TOKEN_ENV_VAR",
    "SWEEP_WRITER_ID",
    "TWENTY_TARGET_ENV_VAR",
    "ConflictingSweepVariablesError",
    "MissingSweepVariableError",
    "PostgresFamilyRowSource",
    "SnowflakeCredential",
    "SnowflakeFamilyRowSource",
    "SweepEnvironment",
    "SweepReaders",
    "TwentyTarget",
    "build_sweep_readers",
    "resolve_sweep_environment",
    "run_projection_conformance_sweep",
]

#: The command API's base URL — the same variable `cli.py`'s other jobs read; one deploy, one API.
PULSE_CORE_BASE_URL_ENV_VAR = "PULSE_CORE_BASE_URL"

#: This sweep's own D15 credential. Distinct from `SCHEDULES_RECONCILIATION_TOKEN` (the consent
#: sweep's *writer*) on purpose: a `projection_conformance` run never declares a command, so it is
#: provisioned read-only (design.md decision 2).
SWEEP_TOKEN_ENV_VAR = "SCHEDULES_SWEEP_TOKEN"  # noqa: S105 — an env var name, not a secret

#: Which Twenty target the board consumer reads, resolved through the pair every credentialed
#: target already uses (`PULSE_TWENTY_<TARGET>_URL` / `_TOKEN`).
TWENTY_TARGET_ENV_VAR = "SCHEDULES_TWENTY_TARGET"

SNOWFLAKE_ACCOUNT_ENV_VAR = "SCHEDULES_SNOWFLAKE_ACCOUNT"
SNOWFLAKE_USER_ENV_VAR = "SCHEDULES_SNOWFLAKE_USER"
SNOWFLAKE_PASSWORD_ENV_VAR = "SCHEDULES_SNOWFLAKE_PASSWORD"  # noqa: S105 — a name, not a secret
SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR = "SCHEDULES_SNOWFLAKE_PRIVATE_KEY_PATH"
SNOWFLAKE_WAREHOUSE_ENV_VAR = "SCHEDULES_SNOWFLAKE_WAREHOUSE"

#: The OCEAN graph database the `patients` projection writes. Absent on dev01-brook, which hosts no
#: graph stack at all — the unconfigured case design.md decision 11 exists for.
GRAPH_DATABASE_URL_ENV_VAR = "SCHEDULES_GRAPH_DATABASE_URL"

#: This sweep's writer identity. It submits no command; the id is what the command API resolves the
#: read credential as (ADR-0003: attribution is authentication), never a write grant.
SWEEP_WRITER_ID = "schedules-reconcile-sweep"

#: The published fold view (task 1.2, `docs/contracts/publishes.md`) — fully qualified by contract,
#: so it is a constant here rather than three more environment variables.
FOLD_VIEW = "STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE"

#: The board's denormalized canonical-identifier column — the same one `twenty_projection.apply`
#: resolves a subject through, which is what makes a board row's key comparable to a ledger
#: subject key at all.
BOARD_SUBJECT_KEY_FIELD = "canonicalPatientId"

#: The `patients` projection's own table and columns (`m1-retire-patient-state`, migration 0021).
PATIENTS_TABLE = "patients"
PATIENTS_COLUMNS: tuple[str, ...] = ("patient_id", "enrollment_status", "ledger_seq")

#: The fold view's columns a sweep reads — `LandingReader`'s own row shape, nothing wider.
FOLD_VIEW_COLUMNS: tuple[str, ...] = ("subject_key", "state", "seq")

#: The one field name every reader's rows are compared under: `LedgerStateReader` folds to
#: `{"state": ...}`, and `LandingReader` / `PatientsReader` already produce it. The board is the
#: exception this module normalizes (`_board_read_in_ledger_vocabulary`).
STATE_FIELD = "state"


class MissingSweepVariableError(RuntimeError):
    """A required environment variable is unset; startup fails naming it, never its value."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"required environment variable {name} is not set")


class ConflictingSweepVariablesError(RuntimeError):
    """Mutually exclusive variables are both set; startup fails naming both, never a value."""

    def __init__(self, first: str, second: str) -> None:
        self.names = (first, second)
        super().__init__(f"environment variables {first} and {second} are mutually exclusive; set exactly one")


@dataclass(frozen=True)
class TwentyTarget:
    """One Twenty instance's read address: the pair `resolve_target` produced."""

    url: str
    token: str


@dataclass(frozen=True)
class SnowflakeCredential:
    """The warehouse reader's connection. Exactly one of `password` / `private_key_path` is set —
    `resolve_sweep_environment` enforces the pair, `_snowflake_connect` picks the auth family."""

    account: str
    user: str
    warehouse: str
    password: str | None = None
    private_key_path: str | None = None


@dataclass(frozen=True)
class SweepEnvironment:
    """Every source this environment has, resolved once, before any connection.

    The ledger pair is always present (a run without a snapshot is not a sweep). Each consumer
    source is `None` when its whole group is absent — the `unconfigured` case, never a failure.
    """

    pulse_core_base_url: str
    pulse_core_token: str
    twenty: TwentyTarget | None = None
    snowflake: SnowflakeCredential | None = None
    graph_database_url: str | None = None


def _required(env: Mapping[str, str], name: str) -> str:
    """One variable that must be set. An empty value counts as missing: an unset secret reaches a
    job as an empty string, and treating that as present would connect with garbage."""
    value = env.get(name)
    if not value:
        raise MissingSweepVariableError(name)
    return value


def _resolve_twenty(env: Mapping[str, str]) -> TwentyTarget | None:
    """The board's target, or `None` when no target is named at all.

    A target named but not credentialed is a deploy fault: `resolve_target` says which variable is
    missing, and that name is re-raised as this module's own missing-variable failure.
    """
    target = env.get(TWENTY_TARGET_ENV_VAR)
    if not target:
        return None
    try:
        resolved = resolve_target(target, env)
    except DeployError as exc:
        raise MissingSweepVariableError(_first_missing_twenty_var(env, target)) from exc
    return TwentyTarget(url=resolved.url, token=resolved.token)


def _first_missing_twenty_var(env: Mapping[str, str], target: str) -> str:
    """Which of the target's pair is unset — the name startup fails by. An unknown target name has
    no pair at all, so the target variable itself is what the deploy has to fix."""
    try:
        url_var, token_var = env_var_names(target)
    except DeployError:  # pragma: no cover — env_var_names does not validate the name
        return TWENTY_TARGET_ENV_VAR
    for name in (url_var, token_var):
        if not env.get(name):
            return name
    return TWENTY_TARGET_ENV_VAR


def _resolve_snowflake(env: Mapping[str, str]) -> SnowflakeCredential | None:
    """The warehouse reader's credential, or `None` when the group is absent entirely.

    The account is the group's presence probe: set it and the rest of the group is required, so a
    half-configured warehouse fails by name rather than reporting `unconfigured` and hiding a
    consumer the deploy meant to run.
    """
    account = env.get(SNOWFLAKE_ACCOUNT_ENV_VAR)
    if not account:
        return None
    user = _required(env, SNOWFLAKE_USER_ENV_VAR)
    warehouse = _required(env, SNOWFLAKE_WAREHOUSE_ENV_VAR)
    password = env.get(SNOWFLAKE_PASSWORD_ENV_VAR)
    private_key_path = env.get(SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR)
    if password and private_key_path:
        raise ConflictingSweepVariablesError(SNOWFLAKE_PASSWORD_ENV_VAR, SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR)
    if not password and not private_key_path:
        raise MissingSweepVariableError(SNOWFLAKE_PASSWORD_ENV_VAR)
    return SnowflakeCredential(
        account=account,
        user=user,
        warehouse=warehouse,
        password=password or None,
        private_key_path=private_key_path or None,
    )


def resolve_sweep_environment(env: Mapping[str, str] | None = None) -> SweepEnvironment:
    """Read every variable this run could need, before any connection is opened.

    `env` defaults to `os.environ`; tests pass a plain `dict` so the resolution never touches the
    real process environment. Order is the ledger pair first, then the board, warehouse and graph
    groups — the order a misconfigured deploy sees its first failure in.
    """
    source = environ if env is None else env
    return SweepEnvironment(
        pulse_core_base_url=_required(source, PULSE_CORE_BASE_URL_ENV_VAR),
        pulse_core_token=_required(source, SWEEP_TOKEN_ENV_VAR),
        twenty=_resolve_twenty(source),
        snowflake=_resolve_snowflake(source),
        graph_database_url=source.get(GRAPH_DATABASE_URL_ENV_VAR) or None,
    )


# --- sources ------------------------------------------------------------------------------------


def _snowflake_connect(credential: SnowflakeCredential) -> Any:
    """The only place `snowflake.connector` is imported (the lazy posture
    `verdict_relay.production` and `pulse_core.catalog_release_cli` already hold), so importing
    this module — or paging a source against an injected `connect` — never needs the driver."""
    connector = importlib.import_module("snowflake.connector")
    shared: dict[str, Any] = {
        "account": credential.account,
        "user": credential.user,
        "warehouse": credential.warehouse,
    }
    if credential.private_key_path is not None:
        serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
        private_key = serialization.load_pem_private_key(Path(credential.private_key_path).read_bytes(), password=None)
        return connector.connect(
            **shared,
            authenticator="SNOWFLAKE_JWT",
            private_key=private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
        )
    return connector.connect(**shared, password=credential.password)


def _postgres_connect(dsn: str) -> Any:
    """The graph database connection, opened read-only. `psycopg` is imported lazily for the same
    reason the drivers above are: constructing this source must not require it."""
    psycopg = importlib.import_module("psycopg")
    connection = psycopg.connect(dsn, autocommit=True)
    connection.read_only = True
    return connection


def _rows(cursor: Any, columns: Sequence[str]) -> list[dict[str, object]]:
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


class SnowflakeFamilyRowSource:
    """The `warehouse-landing` consumer's source: one parameterized `SELECT` per family off the
    published fold view, and no other statement this class can issue.

    The connection opens lazily on the first `fetch_family` and is reused, so constructing this
    source (which `build_sweep_readers` does for every configured environment) reaches no network.
    """

    def __init__(
        self,
        credential: SnowflakeCredential,
        *,
        connect: Callable[[SnowflakeCredential], Any] | None = None,
    ) -> None:
        self._credential = credential
        self._connect = connect or _snowflake_connect
        self._connection: Any | None = None

    def _ensure_connection(self) -> Any:
        if self._connection is None:
            self._connection = self._connect(self._credential)
        return self._connection

    def fetch_family(self, family: str) -> Sequence[Mapping[str, object]]:
        connection = self._ensure_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SELECT {', '.join(FOLD_VIEW_COLUMNS)} FROM {FOLD_VIEW} WHERE subject_type = %s",  # noqa: S608
                (family,),
            )
            return _rows(cursor, FOLD_VIEW_COLUMNS)
        finally:
            cursor.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class PostgresFamilyRowSource:
    """The `graph-projection-patients` consumer's source: the `patients` projection's three
    columns, off a session set read-only before its first statement.

    `family` is accepted and unused: `patients` is the `enrollment` projection's whole table, and
    the consumer is registered against `enrollment` alone (task 3.2), so there is no per-family
    predicate to apply — taking the argument keeps the `FamilyRowSource` seam one shape.
    """

    def __init__(self, dsn: str, *, connect: Callable[[str], Any] | None = None) -> None:
        self._dsn = dsn
        self._connect = connect or _postgres_connect
        self._connection: Any | None = None

    def _ensure_connection(self) -> Any:
        """Open the session and pin it read-only before its first statement — belt and braces with
        `_postgres_connect`, so an injected `connect` cannot hand back a writable session."""
        if self._connection is None:
            connection = self._connect(self._dsn)
            connection.read_only = True
            self._connection = connection
        return self._connection

    def fetch_family(self, family: str) -> Sequence[Mapping[str, object]]:
        del family
        connection = self._ensure_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT {', '.join(PATIENTS_COLUMNS)} FROM {PATIENTS_TABLE}")  # noqa: S608
            return _rows(cursor, PATIENTS_COLUMNS)
        finally:
            cursor.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


# --- readers ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepReaders:
    """This environment's readers: the ledger's always, each consumer's only when its source is
    configured. A `None` is what the run reports as `unconfigured`."""

    ledger: LedgerStateReader
    board: BoardReader | None = None
    landing: LandingReader | None = None
    patients: PatientsReader | None = None


def build_sweep_readers(
    environment: SweepEnvironment,
    *,
    connect_snowflake: Callable[[SnowflakeCredential], Any] | None = None,
    connect_postgres: Callable[[str], Any] | None = None,
) -> SweepReaders:
    """The production readers for one run. Opens nothing: every source connects lazily on its
    first read, and `PulseCoreClient` speaks HTTP only when asked.

    The two `connect_*` seams exist for the same reason `SnowflakeRowSource`'s does — a test pages
    a source without the driver installed and without a socket.
    """
    client = PulseCoreClient(
        environment.pulse_core_base_url,
        writer_id=SWEEP_WRITER_ID,
        token=environment.pulse_core_token,
    )
    board = None
    if environment.twenty is not None:
        board = BoardReader(ProjectionRestClient(environment.twenty.url, token=environment.twenty.token))
    landing = None
    if environment.snowflake is not None:
        landing = LandingReader(SnowflakeFamilyRowSource(environment.snowflake, connect=connect_snowflake))
    patients = None
    if environment.graph_database_url is not None:
        patients = PatientsReader(PostgresFamilyRowSource(environment.graph_database_url, connect=connect_postgres))
    return SweepReaders(ledger=LedgerStateReader(client), board=board, landing=landing, patients=patients)


# --- the run ------------------------------------------------------------------------------------


def _board_target(family: str) -> BoardTarget | None:
    """The board that projects this family, if any — the projection's own registration, never a
    hand-kept list (`consumer_registry.BOARD_TARGETS`)."""
    for target in BOARD_TARGETS:
        if target.subject_type == family:
            return target
    return None


def _ledger_state_by_encoding(family: str) -> dict[str, str]:
    """The board's encoded option values mapped back to the catalog states they encode.

    The projection stores a catalog state as `encode_option_value(state)` (UPPER_SNAKE), while the
    ledger's fold carries the catalog vocabulary itself. Comparing the two verbatim would report
    every board row as `state` drift, so the board's value is translated back through the catalog's
    own state set — never guessed by lowercasing, which `encode_option_value` is not injective
    under.
    """
    subject = load_catalog().subjects.get(family)
    if subject is None:  # pragma: no cover — the registry refuses a family the catalog lacks
        return {}
    return {encode_option_value(state): state for state in subject.transitions}


def _board_read_in_ledger_vocabulary(read: FamilyRead, *, board: BoardTarget, family: str) -> FamilyRead:
    """One board read restated in the ledger's own field name and vocabulary.

    A value no catalog state encodes to is left as it stands: that board row genuinely holds a
    state the catalog does not model, which is drift to report, not a translation to invent.
    """
    states = _ledger_state_by_encoding(family)
    rows = [
        SweptRow(
            subject_key=row.subject_key,
            fields={STATE_FIELD: states.get(row.fields[board.status_field], row.fields[board.status_field])},
            cited_seq=row.cited_seq,
        )
        for row in read.rows
    ]
    return FamilyRead(rows=rows, malformed=read.malformed)


def _read_consumer(consumer: Consumer, *, family: str, readers: SweepReaders) -> FamilyRead | None:
    """One consumer's rows for this family, or `None` when its source is not configured here.

    Dispatch is by the reader the registry handed the consumer, not by consumer name: a fourth
    consumer registered over one of these readers reads correctly without this function changing.
    """
    reader = consumer.reader
    if reader is None:
        return None
    if isinstance(reader, BoardReader):
        board = _board_target(family)
        if board is None:  # pragma: no cover — the board consumer registers only its own families
            return None
        read = reader.read_family(
            BoardFields(
                board=board,
                subject_key_field=BOARD_SUBJECT_KEY_FIELD,
                compared_fields=(board.status_field,),
            )
        )
        return _board_read_in_ledger_vocabulary(read, board=board, family=family)
    if isinstance(reader, LandingReader | PatientsReader):
        return reader.read_family(family)
    msg = f"consumer {consumer.name!r} carries no reader this wiring knows how to read"  # pragma: no cover
    raise TypeError(msg)  # pragma: no cover


def _snapshot(
    subject_keys: Sequence[str],
    *,
    family: str,
    reader: LedgerStateReader,
) -> dict[str, SubjectSnapshot]:
    """The run's one pinned snapshot (design.md decision 4): each subject's ledger head, read once,
    per subject, through the command API — the only ledger read this sweep performs."""
    snapshot: dict[str, SubjectSnapshot] = {}
    for subject_key in subject_keys:
        read = reader.read_subject(family, subject_key)
        snapshot[subject_key] = snapshot_from_read(subject_key, read, head_recorded_at=read.head_recorded_at)
    return snapshot


def run_projection_conformance_sweep(
    *,
    family: str,
    registry: Mapping[str, Family],
    readers: SweepReaders,
    as_of: datetime,
    floor: date = MIN_COMPLETE_FROM,
) -> FamilyConformance:
    """One ledger family's whole run: read every registered consumer this environment configures,
    pin the snapshot over the subjects they returned, and classify.

    A consumer whose source is unconfigured here is reported by name and skipped (design.md
    decision 11); one the registry never registered for this family is simply absent, and a family
    with none at all is `no_consumers` — the registry's answer, never the environment's.

    The subject universe is the union of the consumers' own rows: the command API exposes no bulk
    enumeration, so a subject no consumer projects is not visible to this sweep at all. That is the
    same boundary decision 2 buys — the referee reads the ledger one subject at a time and holds no
    ledger connection.
    """
    consumers = build_consumers(
        registry,
        board_reader=readers.board,
        landing_reader=readers.landing,
        patients_reader=readers.patients,
    )
    registered = [consumer for consumer in consumers if family in consumer.families]

    reads: list[tuple[Consumer, FamilyRead | None]] = [
        (consumer, _read_consumer(consumer, family=family, readers=readers)) for consumer in registered
    ]
    subject_keys = sorted({row.subject_key for _, read in reads if read is not None for row in read.rows})
    snapshot = _snapshot(subject_keys, family=family, reader=readers.ledger)

    results: list[ConsumerConformance] = []
    for consumer, read in reads:
        if read is None:
            results.append(report_unconfigured_consumer(family=family, consumer=consumer))
        elif consumer.uncitable:
            results.append(report_uncitable_consumer(family=family, consumer=consumer, row_count=len(read.rows)))
        else:
            results.append(
                compare_family(family=family, consumer=consumer, snapshot=snapshot, read=read, as_of=as_of, floor=floor)
            )
    return conform_family(family=family, snapshot=snapshot, consumers=results, floor=floor)
