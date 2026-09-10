"""`schedules.sweep_production` — task 3.4's production wiring for a ledger family's sweep.

Three credential postures meet in one process here (the projection's read client, a read-only
Snowflake reader on the fold view, a read-only Postgres reader on the OCEAN graph database), so
these tests pin three things and nothing else: which variables are read and in what order, which
consumers a run actually builds, and that no source is ever connected before the environment has
been resolved whole.

Offline and credential-free throughout: environments are plain dicts, the Snowflake and Postgres
drivers are never imported (both connect through an injected callable), the board reads over
`httpx.MockTransport`, and `conftest.py` blocks sockets for every test in this package regardless.
Subject keys are synthetic (`enr-1`, ...); no PHI, no real identifier, anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from schedules import sweep_production as production
from schedules.sweep_readers import BoardReader, LandingReader, LedgerStateReader, PatientsReader
from schedules.sweep_registry import build_registry
from twenty_projection.apply import ProjectionRestClient

FAMILY = "enrollment"
AS_OF = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
BOARD_TOKEN = "a-twenty-token"  # noqa: S105 — a fixture value, not a secret

_LEDGER_ENV = {
    production.PULSE_CORE_BASE_URL_ENV_VAR: "https://pulse-core.example",
    production.SWEEP_TOKEN_ENV_VAR: "a-read-token",
}
_TWENTY_ENV = {
    production.TWENTY_TARGET_ENV_VAR: "dev",
    "PULSE_TWENTY_DEV_URL": "https://twenty.example",
    "PULSE_TWENTY_DEV_TOKEN": "a-twenty-token",
}
_SNOWFLAKE_ENV = {
    production.SNOWFLAKE_ACCOUNT_ENV_VAR: "an-account",
    production.SNOWFLAKE_USER_ENV_VAR: "a-reader",
    production.SNOWFLAKE_PASSWORD_ENV_VAR: "a-password",
    production.SNOWFLAKE_WAREHOUSE_ENV_VAR: "a-warehouse",
}
_GRAPH_ENV = {production.GRAPH_DATABASE_URL_ENV_VAR: "postgresql://reader@graph/ocean"}

#: Every source configured — the posture a fully-provisioned environment has, and the one dev01
#: does *not* have (it hosts no OCEAN graph database — design.md decision 11).
FULL_ENV = {**_LEDGER_ENV, **_TWENTY_ENV, **_SNOWFLAKE_ENV, **_GRAPH_ENV}

#: dev01-brook: the graph database is simply absent, which is a skipped consumer, not a failure.
DEV01_ENV = {**_LEDGER_ENV, **_TWENTY_ENV, **_SNOWFLAKE_ENV}


# --- fakes ------------------------------------------------------------------------------------


class _RefusingConnect:
    """A connect callable that fails the test if it is ever called — the "before any connection"
    assertion, stated as a fake rather than as a mock's call count."""

    def __init__(self, what: str) -> None:
        self._what = what

    def __call__(self, *args: object, **kwargs: object) -> Any:
        msg = f"{self._what} was connected before the environment resolved"
        raise AssertionError(msg)


class _FakeCursor:
    def __init__(self, rows: Sequence[tuple[object, ...]], columns: Sequence[str]) -> None:
        self._rows = rows
        self._columns = columns
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, parameters))

    def fetchall(self) -> Sequence[tuple[object, ...]]:
        return self._rows

    @property
    def description(self) -> Sequence[tuple[str, ...]]:
        return [(name,) for name in self._columns]

    def close(self) -> None:
        return None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class _FakeConnection:
    """A DB-API connection stand-in for both drivers: one cursor, recorded SQL, no network."""

    def __init__(self, rows: Sequence[tuple[object, ...]], columns: Sequence[str]) -> None:
        self.cursor_object = _FakeCursor(rows, columns)
        self.read_only: bool | None = None
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_object

    def close(self) -> None:
        self.closed = True


def _landing_connect(rows: Sequence[tuple[object, ...]]) -> tuple[Any, list[_FakeConnection]]:
    connections: list[_FakeConnection] = []

    def connect(_credential: object) -> _FakeConnection:
        connection = _FakeConnection(rows, ("subject_key", "state", "seq"))
        connections.append(connection)
        return connection

    return connect, connections


def _graph_connect(rows: Sequence[tuple[object, ...]]) -> tuple[Any, list[_FakeConnection]]:
    connections: list[_FakeConnection] = []

    def connect(_dsn: str) -> _FakeConnection:
        connection = _FakeConnection(rows, ("patient_id", "enrollment_status", "ledger_seq"))
        connections.append(connection)
        return connection

    return connect, connections


def _board_transport(records: Sequence[Mapping[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("startingAfter"):
            return httpx.Response(200, json={"data": {"patientPrograms": []}})
        return httpx.Response(200, json={"data": {"patientPrograms": list(records)}})

    return httpx.MockTransport(handler)


def _board_record(subject_key: str, *, status: str = "ACTIVE", seq: int = 7) -> dict[str, object]:
    return {"canonicalPatientId": subject_key, "lifecycleStatus": status, "projectionSeq": seq}


class _FakeHistory:
    """A `SubjectHistorySource` over recorded envelopes per subject key."""

    def __init__(self, histories: Mapping[str, Sequence[Mapping[str, object]]]) -> None:
        self.histories = histories
        self.asked: list[tuple[str, str]] = []

    def subject_history(self, subject_type: str, subject_key: str) -> Sequence[Mapping[str, object]]:
        self.asked.append((subject_type, subject_key))
        return self.histories.get(subject_key, ())


def _history(subject_key: str, *, to_state: str = "active", seq: int = 7) -> list[dict[str, object]]:
    return [
        {
            "event_id": "11111111-1111-1111-1111-111111111111",
            "subject_type": FAMILY,
            "subject_key": subject_key,
            "seq": seq,
            "effective_at": "2026-09-01T00:00:00+00:00",
            "recorded_at": "2026-09-01T00:00:05+00:00",
            "reverses_event_id": None,
            "payload": {"to_state": to_state},
        }
    ]


def _readers(
    *,
    histories: Mapping[str, Sequence[Mapping[str, object]]],
    board: Sequence[Mapping[str, object]] | None = None,
    landing: Sequence[tuple[object, ...]] | None = None,
    patients: Sequence[tuple[object, ...]] | None = None,
) -> production.SweepReaders:
    """The three readers a run compares with, each present only when its source is configured."""
    board_reader = None
    if board is not None:
        board_reader = BoardReader(
            ProjectionRestClient("https://twenty.example", token=BOARD_TOKEN, transport=_board_transport(board))
        )
    landing_reader = None
    if landing is not None:
        connect, _ = _landing_connect(landing)
        landing_reader = LandingReader(production.SnowflakeFamilyRowSource(_snowflake_credential(), connect=connect))
    patients_reader = None
    if patients is not None:
        connect, _ = _graph_connect(patients)
        patients_reader = PatientsReader(
            production.PostgresFamilyRowSource("postgresql://reader@graph/ocean", connect=connect)
        )
    return production.SweepReaders(
        ledger=LedgerStateReader(_FakeHistory(histories)),
        board=board_reader,
        landing=landing_reader,
        patients=patients_reader,
    )


def _snowflake_credential() -> production.SnowflakeCredential:
    return production.SnowflakeCredential(
        account="an-account",
        user="a-reader",
        warehouse="a-warehouse",
        password="a-password",  # noqa: S106 — a fixture value, not a secret
    )


# --- environment resolution -------------------------------------------------------------------


class TestResolveSweepEnvironment:
    """Every variable read before any connection, and a missing one named (spec: "A missing
    variable fails startup by name")."""

    def test_a_full_environment_resolves_every_source(self) -> None:
        environment = production.resolve_sweep_environment(FULL_ENV)

        assert environment.pulse_core_base_url == FULL_ENV[production.PULSE_CORE_BASE_URL_ENV_VAR]
        assert environment.twenty is not None
        assert environment.snowflake is not None
        assert environment.graph_database_url == FULL_ENV[production.GRAPH_DATABASE_URL_ENV_VAR]

    @pytest.mark.parametrize(
        "name",
        [production.PULSE_CORE_BASE_URL_ENV_VAR, production.SWEEP_TOKEN_ENV_VAR],
    )
    def test_a_missing_required_variable_fails_by_name(self, name: str) -> None:
        env = {key: value for key, value in FULL_ENV.items() if key != name}

        with pytest.raises(production.MissingSweepVariableError) as exc_info:
            production.resolve_sweep_environment(env)

        assert exc_info.value.name == name
        assert name in str(exc_info.value)

    def test_a_missing_variable_names_no_value(self) -> None:
        env = {key: value for key, value in FULL_ENV.items() if key != production.SWEEP_TOKEN_ENV_VAR}

        with pytest.raises(production.MissingSweepVariableError) as exc_info:
            production.resolve_sweep_environment(env)

        assert FULL_ENV[production.PULSE_CORE_BASE_URL_ENV_VAR] not in str(exc_info.value)

    def test_an_unset_source_group_is_unconfigured_not_missing(self) -> None:
        environment = production.resolve_sweep_environment(DEV01_ENV)

        assert environment.graph_database_url is None
        assert environment.twenty is not None
        assert environment.snowflake is not None

    def test_a_half_set_source_group_fails_by_name(self) -> None:
        env = {key: value for key, value in FULL_ENV.items() if key != production.SNOWFLAKE_USER_ENV_VAR}

        with pytest.raises(production.MissingSweepVariableError) as exc_info:
            production.resolve_sweep_environment(env)

        assert exc_info.value.name == production.SNOWFLAKE_USER_ENV_VAR

    def test_a_twenty_target_without_its_credential_pair_fails_by_name(self) -> None:
        env = {key: value for key, value in FULL_ENV.items() if key != "PULSE_TWENTY_DEV_TOKEN"}

        with pytest.raises(production.MissingSweepVariableError) as exc_info:
            production.resolve_sweep_environment(env)

        assert exc_info.value.name == "PULSE_TWENTY_DEV_TOKEN"

    def test_both_snowflake_credentials_set_is_refused_naming_both(self) -> None:
        env = {**FULL_ENV, production.SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR: "/keys/sweep.pem"}

        with pytest.raises(production.ConflictingSweepVariablesError) as exc_info:
            production.resolve_sweep_environment(env)

        assert set(exc_info.value.names) == {
            production.SNOWFLAKE_PASSWORD_ENV_VAR,
            production.SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR,
        }

    def test_a_key_pair_credential_resolves_without_a_password(self) -> None:
        env = {key: value for key, value in FULL_ENV.items() if key != production.SNOWFLAKE_PASSWORD_ENV_VAR}
        env[production.SNOWFLAKE_PRIVATE_KEY_PATH_ENV_VAR] = "/keys/sweep.pem"

        environment = production.resolve_sweep_environment(env)

        assert environment.snowflake is not None
        assert environment.snowflake.private_key_path == "/keys/sweep.pem"
        assert environment.snowflake.password is None

    def test_resolution_connects_nothing(self) -> None:
        readers = production.build_sweep_readers(
            production.resolve_sweep_environment(FULL_ENV),
            connect_snowflake=_RefusingConnect("snowflake"),
            connect_postgres=_RefusingConnect("the graph database"),
        )

        # Constructed, but no `fetch_family` call yet — so neither driver has been reached.
        assert readers.landing is not None
        assert readers.patients is not None


# --- reader construction ----------------------------------------------------------------------


class TestBuildSweepReaders:
    def test_an_unconfigured_source_yields_no_reader(self) -> None:
        readers = production.build_sweep_readers(
            production.resolve_sweep_environment(DEV01_ENV),
            connect_snowflake=_RefusingConnect("snowflake"),
            connect_postgres=_RefusingConnect("the graph database"),
        )

        assert readers.patients is None
        assert readers.board is not None
        assert readers.landing is not None

    def test_no_reader_holds_a_write_method(self) -> None:
        """Design.md decision 2: the referee holds read credentials only. A reader whose public
        surface grew a write verb would be the first way that stops being true."""
        readers = production.build_sweep_readers(
            production.resolve_sweep_environment(FULL_ENV),
            connect_snowflake=_RefusingConnect("snowflake"),
            connect_postgres=_RefusingConnect("the graph database"),
        )

        for reader in (readers.ledger, readers.board, readers.landing, readers.patients):
            assert reader is not None
            verbs = {name for name in dir(reader) if not name.startswith("_") and callable(getattr(reader, name))}
            assert verbs <= {"read_family", "read_subject"}


# --- the sources ------------------------------------------------------------------------------


class TestSnowflakeFamilyRowSource:
    def test_it_selects_the_fold_view_for_one_family_and_nothing_else(self) -> None:
        connect, connections = _landing_connect([("enr-1", "active", 7)])
        source = production.SnowflakeFamilyRowSource(_snowflake_credential(), connect=connect)

        rows = source.fetch_family(FAMILY)

        assert list(rows) == [{"subject_key": "enr-1", "state": "active", "seq": 7}]
        sql, parameters = connections[0].cursor_object.executed[0]
        assert sql.strip().upper().startswith("SELECT")
        assert production.FOLD_VIEW in sql
        assert parameters == (FAMILY,)

    def test_it_connects_once_across_reads(self) -> None:
        connect, connections = _landing_connect([("enr-1", "active", 7)])
        source = production.SnowflakeFamilyRowSource(_snowflake_credential(), connect=connect)

        source.fetch_family(FAMILY)
        source.fetch_family(FAMILY)

        assert len(connections) == 1


class TestPostgresFamilyRowSource:
    def test_it_reads_the_patients_projection_columns_read_only(self) -> None:
        connect, connections = _graph_connect([("enr-1", "active", 7)])
        source = production.PostgresFamilyRowSource("postgresql://reader@graph/ocean", connect=connect)

        rows = source.fetch_family(FAMILY)

        assert list(rows) == [{"patient_id": "enr-1", "enrollment_status": "active", "ledger_seq": 7}]
        assert connections[0].read_only is True
        sql, _ = connections[0].cursor_object.executed[0]
        assert sql.strip().upper().startswith("SELECT")


# --- the run ------------------------------------------------------------------------------------


class TestRunProjectionConformanceSweep:
    """`reconcile-sweep --family <ledger family>`'s actual comparison, over readers built above."""

    def test_a_ledger_family_runs_every_registered_consumer(self) -> None:
        conformance = production.run_projection_conformance_sweep(
            family=FAMILY,
            registry=build_registry(),
            readers=_readers(
                histories={"enr-1": _history("enr-1")},
                board=[_board_record("enr-1")],
                landing=[("enr-1", "active", 7)],
                patients=[("enr-1", "active", 7)],
            ),
            as_of=AS_OF,
        )

        assert [consumer.consumer for consumer in conformance.consumers] == [
            "twenty-board",
            "warehouse-landing",
            "graph-projection-patients",
        ]
        assert conformance.counts() == {"agreement": 3}
        assert conformance.no_consumers is False

    def test_the_board_is_compared_in_the_ledgers_own_vocabulary(self) -> None:
        """The board stores catalog states UPPER_SNAKE-encoded (`encode_option_value`); comparing
        that against the ledger's `active` verbatim would report every board row as drift."""
        conformance = production.run_projection_conformance_sweep(
            family=FAMILY,
            registry=build_registry(),
            readers=_readers(
                histories={"enr-1": _history("enr-1", to_state="pending_start")},
                board=[_board_record("enr-1", status="PENDING_START")],
            ),
            as_of=AS_OF,
        )

        board = next(consumer for consumer in conformance.consumers if consumer.consumer == "twenty-board")
        assert board.counts() == {"agreement": 1}

    def test_a_real_board_disagreement_is_still_state_drift(self) -> None:
        conformance = production.run_projection_conformance_sweep(
            family=FAMILY,
            registry=build_registry(),
            readers=_readers(
                histories={"enr-1": _history("enr-1", to_state="active")},
                board=[_board_record("enr-1", status="ENDED")],
            ),
            as_of=AS_OF,
        )

        board = next(consumer for consumer in conformance.consumers if consumer.consumer == "twenty-board")
        assert board.counts() == {"state": 1}
        assert board.comparisons[0].fields == ("state",)

    def test_an_unconfigured_consumer_is_named_and_the_others_still_compare(self) -> None:
        """dev01 hosts no OCEAN graph database (design.md decision 11): `graph-projection-patients`
        is skipped and named, never a divergence and never `no_consumers`."""
        conformance = production.run_projection_conformance_sweep(
            family=FAMILY,
            registry=build_registry(),
            readers=_readers(
                histories={"enr-1": _history("enr-1")},
                board=[_board_record("enr-1")],
                landing=[("enr-1", "active", 7)],
            ),
            as_of=AS_OF,
        )

        unconfigured = [consumer.consumer for consumer in conformance.consumers if consumer.unconfigured]
        assert unconfigured == ["graph-projection-patients"]
        assert conformance.counts() == {"agreement": 2}
        assert conformance.no_consumers is False

    def test_the_snapshot_is_read_once_per_subject_through_the_ledger_reader(self) -> None:
        history = _FakeHistory({"enr-1": _history("enr-1")})
        readers = production.SweepReaders(
            ledger=LedgerStateReader(history),
            board=BoardReader(
                ProjectionRestClient(
                    "https://twenty.example", token=BOARD_TOKEN, transport=_board_transport([_board_record("enr-1")])
                )
            ),
            landing=None,
            patients=None,
        )

        production.run_projection_conformance_sweep(
            family=FAMILY, registry=build_registry(), readers=readers, as_of=AS_OF
        )

        assert history.asked == [(FAMILY, "enr-1")]

    def test_a_family_no_consumer_is_registered_against_is_no_consumers(self) -> None:
        """`no_consumers` is the registry's answer, never an unconfigured environment's."""
        conformance = production.run_projection_conformance_sweep(
            family="device",
            registry={"device": build_registry()["device"]},
            readers=_readers(histories={}),
            as_of=AS_OF,
        )

        assert conformance.no_consumers is False  # warehouse-landing registers against every family

        empty = production.run_projection_conformance_sweep(
            family="device",
            registry={},
            readers=_readers(histories={}),
            as_of=AS_OF,
        )
        assert empty.no_consumers is True
