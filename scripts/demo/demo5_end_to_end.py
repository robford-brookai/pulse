#!/usr/bin/env python
"""Demo 5 — end to end (task 2.1): one synthetic patient crosses every seam PULSE owns.

Per `openspec/changes/pulse-demo-closeout/specs/end-to-end-demo/spec.md`: six stages, in order,
each asserting its outcome against the ledger before the next stage begins, stopping at the first
failed assertion. This module is the harness — the `Stage` protocol, `DemoContext`, the offline
and live context builders, and the receipt printer — plus the six stages, composed from the demos
and packages that already own each door rather than reimplemented here (design.md decision 1:
"compose, do not rewrite").

Per the roadmap's demo convention, this script needs the local LocalStack + Postgres compose stack
(`packages/ocean/infra/docker-compose.yml`) offline, or dev credentials with `--live`, and stays
out of `task check` either way — only `tests/test_demo5_end_to_end.py`'s smoke-parse and
harness-unit tests run there.

**Where each stage's door comes from** (design.md decision 1 and 2 — one `DemoContext`, transport
swapped by how it is built, stage code never branches on mode):

1. **Identity resolution of a referral** — `identity.matcher.resolve`, driven the same way
   `demo2_identity_matcher.py` drives it, over the cohort's three referral variants
   (`fixtures/referral_variants.json`): mint, exact match, quarantine.
2. **Consent ingress from an export landing row** — `consent_ingress.declarer.declare_consent_rows`
   over a `FixtureRowSource` holding `fixtures/consent_export_row.json`, the same building blocks
   `consent_ingress.cli.run_consent_ingress_job` composes, swept twice to show the second sweep
   commits nothing new.
3. **A signed board drag** — `demo3_live_kanban_drag.py`'s payload builder and `LedgerDeliverer`,
   posted straight at the ledger's Twenty webhook route running in-process (no live Twenty needed
   offline: the assertion is the ledger's door, not Twenty's board state, which stage 5 checks).
4. **A verdict declared from the mart read** — `verdict_relay.run.run_relay` over a
   `FixtureRowSource` holding `fixtures/verdict_mart_row.json`, the same declarer wiring
   `demo4_billing_declare_back.py` drives against a live mart.
5. **Every window agrees with the ledger** (task 2.2) — board, warehouse-landed events, and an
   independent fold of the journal, each reduced to `(subject_type, subject_key, state, as_of)`
   and compared to the ledger's own `current_state` row.
6. **The rebuild drill** (task 3.1) — `twenty_projection.rebuild`'s operator command (task 2.3),
   run as this walk's own last stage: capture the enrollment scope's board row, delete the
   columns the projection owns, rebuild, and assert the repainted row equals the captured one.

**The in-process board route** (offline context builder): `pulse_ledger.api.create_app` built
against the compose stack's own `ledger-postgres`, served over `starlette.testclient.TestClient`'s
synchronous ASGI transport rather than a live process — no port, no live Twenty, same route code
the deployed service runs.

**The live context builder** (task 3.1, `--live`): the dev ledger over `httpx` (the same pair
`demo3_live_kanban_drag.py` reads, `PULSE_LEDGER_API_URL` / `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET`)
and its Postgres (`DATABASE_URL`), dev Twenty over `httpx` (`pulse_core.twenty_deploy`'s
`PULSE_TWENTY_DEV_URL` / `PULSE_TWENTY_DEV_TOKEN`), and `STG_EVENTS.EVENTS` read-only as the
warehouse window (`DEMO5_SNOWFLAKE_*`) — every credential name is pinned in this module and every
value comes from the environment only, never a flag, never code (`resolve_live_config`).

Usage:
    scripts/demo/demo5_end_to_end.py [--skip-compose-up] [--database-url URL]
    scripts/demo/demo5_end_to_end.py --live
    scripts/demo/demo5_end_to_end.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import secrets
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
import psycopg
from psycopg_pool import ConnectionPool
from starlette.testclient import TestClient

DEMO_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = DEMO_DIR / "fixtures"

# The four demos already expose their stage logic as free functions (design.md decision 1) — cross
# import by path, the same pattern `tests/test_demo3_live_kanban_drag.py` uses for a demo script
# that is not an installed package.
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

import demo1_ledger_core as demo1  # noqa: E402
import demo2_identity_matcher as demo2  # noqa: E402
import demo3_live_kanban_drag as demo3  # noqa: E402
from consent_ingress.cli import CUSTOMERIO_TOKEN_ENV_VAR  # noqa: E402
from consent_ingress.declarer import (  # noqa: E402
    CUSTOMERIO_WRITER_ID,
    build_run_receipt,
    declare_consent_rows,
    ledger_subject_key,
)
from consent_ingress.row_source import ConsentRowReader  # noqa: E402
from consent_ingress.row_source import FixtureRowSource as ConsentFixtureRowSource  # noqa: E402
from identity.matcher import Ambiguous, Match  # noqa: E402
from pulse_core.client import PulseCoreClient  # noqa: E402
from pulse_core.generated import OpenBillingEpisodeCommand, RecordCommunicationConsentCommand  # noqa: E402
from pulse_core.replay import REPLAY_TOKEN_ENV_VAR  # noqa: E402
from pulse_core.twenty_deploy import DeployError, Target, resolve_target  # noqa: E402
from pulse_ledger.api import TWENTY_WEBHOOK_PATH, create_app  # noqa: E402
from pulse_ledger.api_server import (  # noqa: E402
    build_committer,
    build_cursor_reader,
    build_cursor_writer,
    build_history_reader,
    build_state_reader,
)
from pulse_ledger.auth import (  # noqa: E402
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    CredentialRegistry,
    TwentyWebhookConfig,
    Writer,
)
from pulse_ledger.fold import FoldedEvent, fold_state, state_borne_by  # noqa: E402
from pulse_ledger.reads import state_of_record, subject_history  # noqa: E402
from pulse_ledger.validation import INITIAL_STATES  # noqa: E402
from twenty_projection.apply import V1_BOARD, ProjectionRestClient, apply_event  # noqa: E402
from twenty_projection.rebuild import (  # noqa: E402
    PROGRAM_COLUMN,
    SUBJECT_COLUMN,
    parse_scope,
)
from twenty_projection.rebuild import PROJECTION_WRITER_ID as REBUILD_WRITER_ID  # noqa: E402
from twenty_projection.rebuild import rebuild as run_projection_rebuild  # noqa: E402
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT, TRANSITION_BY_OUTCOME  # noqa: E402
from verdict_relay.declarer import Declarer  # noqa: E402
from verdict_relay.mart_reader import FixtureRowSource as MartFixtureRowSource  # noqa: E402
from verdict_relay.mart_reader import MartReader  # noqa: E402
from verdict_relay.production import PULSE_CORE_TOKEN_ENV_VAR as VERDICT_RELAY_TOKEN_ENV_VAR  # noqa: E402
from verdict_relay.production import WRITER_ID as VERDICT_RELAY_WRITER_ID  # noqa: E402
from verdict_relay.run import run_relay  # noqa: E402

#: Writer ids this walk needs credentials for: the three producing stages' own writer identity
#: plus the rebuild drill's replay identity (task 3.1) — the kit's read-only facility
#: (`pulse_core.replay`), reused here under its own name rather than a fourth invented one.
WRITER_IDS = (CUSTOMERIO_WRITER_ID, VERDICT_RELAY_WRITER_ID, REBUILD_WRITER_ID)

BILLING_EPISODE_SUBJECT_TYPE = "billing_episode"

#: The read surface stage 5 and stage 6 compare board rows against: a mapping keyed by
#: `(subject_type, subject_key)` to that subject's landed envelopes — the LocalStack queue
#: offline, `STG_EVENTS.EVENTS` read-only live (design decision 6). Stage code calls this and
#: never branches on which it got (design decision 2).
WarehouseReader = Callable[[frozenset[tuple[str, str]]], Mapping[tuple[str, str], list[Mapping[str, Any]]]]


class DemoAssertionError(AssertionError):
    """One of demo5's stage assertions failed. Caught once by `run_walk`, never re-raised bare."""


def _check(condition: object, message: str) -> None:
    if not condition:
        raise DemoAssertionError(message)


# --- The harness: Stage protocol, DemoContext, receipts ------------------------------------------


@dataclass(frozen=True)
class StageReceipt:
    """One stage's outcome: its name, how many assertions it made, and the subject keys it
    touched — the shape `run_walk`'s final receipt is built from (spec: "a receipt naming each
    stage, its assertion count, and the subject keys it touched")."""

    stage: str
    assertion_count: int
    subject_keys: tuple[str, ...] = ()


class Stage(Protocol):
    """One stage of the walk (design.md decision 1): `setup` prepares whatever the stage needs
    from the context, `run` performs and asserts, both against the same `DemoContext`."""

    name: str

    def setup(self, ctx: DemoContext) -> None: ...

    def run(self, ctx: DemoContext) -> StageReceipt: ...


class StageFailure(RuntimeError):
    """Raised by `run_walk` when a stage's assertion fails — names the stage and the assertion,
    never re-derives either (spec: "prints which assertion failed and which stage owns it")."""

    def __init__(self, stage_name: str, message: str) -> None:
        self.stage_name = stage_name
        self.message = message
        super().__init__(f"[{stage_name}] {message}")


class _InMemoryCursorStore:
    """A `CursorStore` that persists only within this process — offline sweeps do not need the
    ledger's own writer-state route, and a fresh instance per sweep is how stage 2 proves a second
    sweep of the same fixture row is read again rather than skipped by cursor position."""

    def __init__(self) -> None:
        self._cursor: Mapping[str, object] | None = None

    def load(self) -> Mapping[str, object] | None:
        return self._cursor

    def save(self, cursor: Mapping[str, object]) -> None:
        self._cursor = cursor


class _BoardDouble:
    """An in-memory Twenty board double (task 2.2): the offline "board client" decision 2 names —
    understands exactly the two verbs `twenty_projection.apply.ProjectionRestClient` issues, a
    filtered listing and a record PATCH, against the same REST shape the live board answers. No
    live Twenty needed offline (stage 3's own docstring), yet stage 5 still exercises the real
    `apply_event` core against a real record store, not a stub of it.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def seed(self, record_id: str, fields: Mapping[str, Any]) -> None:
        self.records[record_id] = {"id": record_id, **fields}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")  # ["rest", plural] or ["rest", plural, id]
        plural = parts[1]
        if request.method == "GET":
            filters = _parse_filter(request.url.params.get("filter", ""))
            matches = [
                record for record in self.records.values() if all(record.get(k) == v for k, v in filters.items())
            ]
            return httpx.Response(200, json={"data": {plural: matches}})
        if request.method == "PATCH":
            record_id = parts[2]
            record = self.records.setdefault(record_id, {"id": record_id})
            record.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(405)  # pragma: no cover — apply.py issues only GET and PATCH


def _parse_filter(raw: str) -> dict[str, str]:
    """`field[eq]:value,field2[eq]:value2` (the filter grammar `apply.py`'s docstring pins) back
    into a plain equality mapping — the inverse of `find_records`'s own comma-join."""
    terms: dict[str, str] = {}
    for term in raw.split(",") if raw else ():
        field_name, _, value = term.partition("[eq]:")
        if field_name:
            terms[field_name] = value
    return terms


@dataclass
class DemoContext:
    """The shared context every stage runs against (design.md decision 2): stack handles and the
    patient's subject keys, never a `live`/offline branch inside a stage."""

    live: bool
    database_url: str
    pool: ConnectionPool
    api_transport: httpx.BaseTransport | None
    api_base_url: str
    webhook_secret: str
    writer_tokens: Mapping[str, str]
    fixtures: Mapping[str, Any]
    patient_key: str
    warehouse_reader: WarehouseReader
    board_transport: httpx.BaseTransport | None = None
    board_base_url: str = "http://demo5-board.local"
    board_token: str = "demo5-board-window"  # noqa: S105 — a fixture placeholder offline, a real token live
    board_store: _BoardDouble | None = None
    aws_endpoint_url: str = demo1.DEFAULT_AWS_ENDPOINT_URL
    event_bus_name: str = demo1.DEFAULT_EVENT_BUS_NAME
    consumer: str = demo1.DEFAULT_CONSUMER
    _closers: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def api_client(self, writer_id: str, **kwargs: Any) -> PulseCoreClient:
        return PulseCoreClient(
            self.api_base_url,
            writer_id=writer_id,
            token=self.writer_tokens[writer_id],
            transport=self.api_transport,
            **kwargs,
        )

    def webhook_client(self) -> httpx.Client:
        return httpx.Client(transport=self.api_transport, base_url=self.api_base_url)

    def board_client(self) -> ProjectionRestClient:
        """The one board client every stage that touches Twenty's REST surface uses — offline the
        in-process double, live the real dev instance (design decision 2: transport and token both
        live on the context, never a per-stage branch)."""
        return ProjectionRestClient(self.board_base_url, token=self.board_token, transport=self.board_transport)

    def close(self) -> None:
        for closer in reversed(self._closers):
            closer()


def _make_registry(tokens: Mapping[str, str]) -> CredentialRegistry:
    """Build a `CredentialRegistry` directly from writer id -> token, bypassing the env-var suffix
    convention (`_writer_id_from_suffix` lowercases and maps `_` to `-`): offline mode has no
    environment to read the credentials from in the first place, so it constructs the registry
    from the in-process `writer_tokens` mapping instead."""
    writers = {writer_id: Writer(writer_id=writer_id) for writer_id in tokens}
    digests = {hashlib.sha256(token.encode()).hexdigest(): writer_id for writer_id, token in tokens.items()}
    return CredentialRegistry(writers, digests)


def build_offline_context(
    *,
    compose_file: Path = demo1.DEFAULT_COMPOSE_FILE,
    database_url: str = demo1.DEFAULT_DATABASE_URL,
    skip_compose_up: bool = False,
) -> DemoContext:
    """Offline context builder (task 2.1): compose stack up, fixture landing tables loaded,
    in-process board route.

    Brings up the same LocalStack + Postgres services `demo1_ledger_core.py` needs
    (`demo1.COMPOSE_SERVICES`), builds the ledger's command API in-process against that stack's
    Postgres, and serves it over a `starlette.testclient.TestClient` — a synchronous ASGI
    transport, no live server, no live Twenty, no credential in the environment (spec: "Offline
    needs no credential").
    """
    if not skip_compose_up:
        demo1._compose_up(compose_file)

    pool = ConnectionPool(database_url, min_size=1, max_size=5)
    pool.wait()

    webhook_secret = secrets.token_urlsafe(32)
    writer_tokens = {writer_id: secrets.token_urlsafe(32) for writer_id in WRITER_IDS}

    app = create_app(
        committer=build_committer(pool),
        registry=_make_registry(writer_tokens),
        twenty_webhook=TwentyWebhookConfig.from_env({
            TWENTY_WEBHOOK_ENABLED_ENV: "true",
            TWENTY_WEBHOOK_SECRET_ENV: webhook_secret,
        }),
        cursor_reader=build_cursor_reader(pool),
        cursor_writer=build_cursor_writer(pool),
        state_reader=build_state_reader(pool),
        history_reader=build_history_reader(pool),
    )
    # `TestClient` wraps the ASGI app in a synchronous transport (`httpx.ASGITransport` alone
    # answers only `handle_async_request`, unusable from a plain `httpx.Client`) — the same
    # in-process pattern `packages/pulse-ledger/tests/` uses for this app.
    test_client = TestClient(app, base_url="http://demo5-ledger.local")
    test_client.__enter__()
    transport = test_client._transport

    fixtures = {
        "referral_variants": json.loads((FIXTURES_DIR / "referral_variants.json").read_text())["variants"],
        "consent_export_row": json.loads((FIXTURES_DIR / "consent_export_row.json").read_text()),
        "verdict_mart_row": json.loads((FIXTURES_DIR / "verdict_mart_row.json").read_text()),
    }
    patient_key = fixtures["consent_export_row"]["subject_key"]

    # Stage 5's board window (task 2.2): a record already exists for the patient's enrollment
    # before any drag, canonical/program columns populated and status blank — exactly what a live
    # Twenty board would already hold. `BoardDragStage` commits under `ctx.patient_key` (the
    # `canonicalPatientId` the enrollment mapping's `canonical_key_path` resolves on), so the
    # record id only needs to be unique and stable, not itself meaningful.
    board_store = _BoardDouble()
    board_store.seed(
        f"demo5-board-{patient_key}",
        {"canonicalPatientId": patient_key, "programCode": "demo5"},
    )

    sqs = demo1._sqs_client(demo1.DEFAULT_AWS_ENDPOINT_URL)
    queue_url = sqs.get_queue_url(QueueName=f"{demo1.DEFAULT_EVENT_BUS_NAME}-{demo1.DEFAULT_CONSUMER}")["QueueUrl"]

    def offline_warehouse_reader(
        subjects: frozenset[tuple[str, str]],
    ) -> Mapping[tuple[str, str], list[Mapping[str, Any]]]:
        return _drain_landed_events(sqs, queue_url, subjects, timeout=30.0)

    ctx = DemoContext(
        live=False,
        database_url=database_url,
        pool=pool,
        api_transport=transport,
        api_base_url="http://demo5-ledger.local",
        webhook_secret=webhook_secret,
        writer_tokens=writer_tokens,
        fixtures=fixtures,
        patient_key=patient_key,
        warehouse_reader=offline_warehouse_reader,
        board_transport=board_store.transport(),
        board_store=board_store,
    )
    ctx._closers.append(pool.close)
    ctx._closers.append(lambda: test_client.__exit__(None, None, None))
    return ctx


# --- Live mode: config and context builder (task 3.1) -------------------------------------------

#: The dev ledger — the same pair `demo3_live_kanban_drag.py` reads for its own webhook delivery
#: and command traffic, reused rather than named again (task 3.1: "httpx board client as demo3
#: uses").
LEDGER_URL_ENV = demo3.LEDGER_URL_ENV
#: The ledger database this walk's non-HTTP reads still need (stage 4's `state_of_record`, stage
#: 5's fold and `current_state` windows) — the one credential every deployed `pulse_ledger`
#: process is configured by (`packages/pulse-ledger/src/pulse_ledger/api_server.py`).
DATABASE_URL_ENV = "DATABASE_URL"
#: The one Twenty target this demo drives live — staging/prod would be a promotion decision made
#: elsewhere, never a flag on a demo script (`demo3`'s own `--target` restriction).
TWENTY_TARGET = "dev"

#: This demo's own read-only Snowflake facility for the warehouse window (design decision 6): a
#: different table and a different purpose than verdict-relay's mart credential, so it holds its
#: own name rather than borrowing that one.
STG_EVENTS_ACCOUNT_ENV = "DEMO5_SNOWFLAKE_ACCOUNT"
STG_EVENTS_USER_ENV = "DEMO5_SNOWFLAKE_USER"
STG_EVENTS_PASSWORD_ENV = "DEMO5_SNOWFLAKE_PASSWORD"  # noqa: S105
STG_EVENTS_PRIVATE_KEY_PATH_ENV = "DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH"
STG_EVENTS_WAREHOUSE_ENV = "DEMO5_SNOWFLAKE_WAREHOUSE"

#: The published contract's own coordinates (docs/contracts/publishes.md `snowflake-stg-events`)
#: — fixed by the view's own definition, never configuration.
STG_EVENTS_DATABASE = "STREAMLINE"
STG_EVENTS_SCHEMA = "STG_EVENTS"
STG_EVENTS_TABLE = "EVENTS"

#: The columns `_fold_envelopes` needs off one envelope — a subset of the contract's own column
#: list, the same shape `subject_history` returns offline.
STG_EVENTS_COLUMNS: tuple[str, ...] = (
    "event_id",
    "subject_type",
    "subject_key",
    "effective_at",
    "recorded_at",
    "reverses_event_id",
    "payload",
)


class LiveStartupError(RuntimeError):
    """`--live`'s environment is incomplete — names every absent variable, never a value."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"--live is not configured — set: {', '.join(missing)}")


@dataclass(frozen=True)
class LiveConfig:
    """Every credential a live run holds, resolved from the environment once, by name only
    (task 3.1: "credential names in config and values from the environment only")."""

    database_url: str
    ledger_url: str
    webhook_secret: str
    twenty_target: Target
    customerio_token: str
    verdict_relay_token: str
    projection_replay_token: str
    snowflake_account: str
    snowflake_user: str
    snowflake_warehouse: str
    snowflake_password: str | None
    snowflake_private_key_path: str | None


def resolve_live_config(env: Mapping[str, str]) -> LiveConfig:
    """Read every variable `--live` needs, failing once, naming every absent one before any
    connection is attempted (`verdict_relay.production.resolve_production_config`'s posture)."""
    required = (
        DATABASE_URL_ENV,
        LEDGER_URL_ENV,
        TWENTY_WEBHOOK_SECRET_ENV,
        CUSTOMERIO_TOKEN_ENV_VAR,
        VERDICT_RELAY_TOKEN_ENV_VAR,
        REPLAY_TOKEN_ENV_VAR,
        STG_EVENTS_ACCOUNT_ENV,
        STG_EVENTS_USER_ENV,
        STG_EVENTS_WAREHOUSE_ENV,
    )
    missing = [name for name in required if not env.get(name)]

    password = env.get(STG_EVENTS_PASSWORD_ENV) or None
    key_path = env.get(STG_EVENTS_PRIVATE_KEY_PATH_ENV) or None
    if password is None and key_path is None:
        missing.append(f"{STG_EVENTS_PASSWORD_ENV} or {STG_EVENTS_PRIVATE_KEY_PATH_ENV}")

    try:
        twenty_target = resolve_target(TWENTY_TARGET, env)
    except DeployError as error:
        missing.append(str(error))

    if missing:
        raise LiveStartupError(tuple(missing))

    return LiveConfig(
        database_url=env[DATABASE_URL_ENV],
        ledger_url=env[LEDGER_URL_ENV],
        webhook_secret=env[TWENTY_WEBHOOK_SECRET_ENV],
        twenty_target=twenty_target,
        customerio_token=env[CUSTOMERIO_TOKEN_ENV_VAR],
        verdict_relay_token=env[VERDICT_RELAY_TOKEN_ENV_VAR],
        projection_replay_token=env[REPLAY_TOKEN_ENV_VAR],
        snowflake_account=env[STG_EVENTS_ACCOUNT_ENV],
        snowflake_user=env[STG_EVENTS_USER_ENV],
        snowflake_warehouse=env[STG_EVENTS_WAREHOUSE_ENV],
        snowflake_password=password,
        snowflake_private_key_path=key_path,
    )


def _snowflake_connect_stg_events(config: LiveConfig) -> Any:
    """The only place `snowflake.connector` is ever imported for this reader (mirrors
    `verdict_relay.production._snowflake_connect`'s own lazy-import posture) — so building a
    `resolve_live_config` result, or even this reader against a fake `connect`, never requires the
    driver installed."""
    connector = importlib.import_module("snowflake.connector")
    shared: dict[str, Any] = {
        "account": config.snowflake_account,
        "user": config.snowflake_user,
        "warehouse": config.snowflake_warehouse,
        "database": STG_EVENTS_DATABASE,
        "schema": STG_EVENTS_SCHEMA,
    }
    if config.snowflake_private_key_path is not None:
        serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
        key_data = Path(config.snowflake_private_key_path).read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)
        return connector.connect(
            **shared,
            authenticator="SNOWFLAKE_JWT",
            private_key=private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
        )
    return connector.connect(**shared, password=config.snowflake_password)


def _fetch_stg_events(
    subjects: frozenset[tuple[str, str]],
    *,
    connect: Callable[[], Any],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """One read of `STG_EVENTS.EVENTS`, filtered to the wanted `(subject_type, subject_key)`
    pairs — the live warehouse window design decision 6 names: read-only, no queue to drain."""
    collected: dict[tuple[str, str], list[dict[str, Any]]] = {key: [] for key in subjects}
    keys = sorted({subject_key for _, subject_key in subjects})
    if not keys:
        return collected

    connection = connect()
    try:
        columns = ", ".join(STG_EVENTS_COLUMNS)
        placeholders = ", ".join(["%s"] * len(keys))
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SELECT {columns} FROM {STG_EVENTS_TABLE} WHERE subject_key IN ({placeholders})",  # noqa: S608
                keys,
            )
            for row in cursor.fetchall():
                event = dict(zip(STG_EVENTS_COLUMNS, row, strict=True))
                key = (event["subject_type"], event["subject_key"])
                if key in collected:
                    collected[key].append(event)
        finally:
            cursor.close()
    finally:
        connection.close()
    return collected


def _default_live_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(database_url, min_size=1, max_size=5)


def build_live_context(
    config: LiveConfig, *, pool_factory: Callable[[str], ConnectionPool] = _default_live_pool
) -> DemoContext:
    """Live context builder (task 3.1): the dev ledger over HTTP and its Postgres, dev Twenty over
    `httpx` (demo3's own pattern), and `STG_EVENTS.EVENTS` read-only as the warehouse window — the
    same fixtures and the same assertions as offline; only the transports differ (design decision
    2, spec "Two modes, one assertion set").

    `pool_factory` is the one seam a test uses to hold no live Postgres — production passes none
    and gets a real `ConnectionPool` that `.wait()`s for a connection before this returns.
    """
    pool = pool_factory(config.database_url)
    pool.wait()

    fixtures = {
        "referral_variants": json.loads((FIXTURES_DIR / "referral_variants.json").read_text())["variants"],
        "consent_export_row": json.loads((FIXTURES_DIR / "consent_export_row.json").read_text()),
        "verdict_mart_row": json.loads((FIXTURES_DIR / "verdict_mart_row.json").read_text()),
    }
    patient_key = fixtures["consent_export_row"]["subject_key"]

    def live_warehouse_reader(
        subjects: frozenset[tuple[str, str]],
    ) -> Mapping[tuple[str, str], list[Mapping[str, Any]]]:
        return _fetch_stg_events(subjects, connect=lambda: _snowflake_connect_stg_events(config))

    ctx = DemoContext(
        live=True,
        database_url=config.database_url,
        pool=pool,
        api_transport=None,
        api_base_url=config.ledger_url,
        webhook_secret=config.webhook_secret,
        writer_tokens={
            CUSTOMERIO_WRITER_ID: config.customerio_token,
            VERDICT_RELAY_WRITER_ID: config.verdict_relay_token,
            REBUILD_WRITER_ID: config.projection_replay_token,
        },
        fixtures=fixtures,
        patient_key=patient_key,
        warehouse_reader=live_warehouse_reader,
        board_transport=None,
        board_base_url=config.twenty_target.url,
        board_token=config.twenty_target.token,
        board_store=None,
    )
    ctx._closers.append(pool.close)
    return ctx


def run_walk(stages: Sequence[Stage], ctx: DemoContext) -> list[StageReceipt]:
    """The harness loop (task 2.1): run each stage in order, stop at the first failure.

    Raises `StageFailure` naming the stage and the failed assertion the moment one is raised —
    later stages never run (spec: "A broken seam stops the walk").
    """
    receipts: list[StageReceipt] = []
    for stage in stages:
        print(f"\n[{stage.name}]")
        try:
            stage.setup(ctx)
            receipt = stage.run(ctx)
        except AssertionError as exc:
            raise StageFailure(stage.name, str(exc)) from exc
        receipts.append(receipt)
        print(f"  ok: {receipt.assertion_count} assertion(s), subjects={list(receipt.subject_keys)}")
    return receipts


def print_receipt(receipts: Sequence[StageReceipt]) -> None:
    print("\n=== Demo 5 receipt ===")
    for receipt in receipts:
        print(
            json.dumps({
                "stage": receipt.stage,
                "assertion_count": receipt.assertion_count,
                "subject_keys": list(receipt.subject_keys),
            })
        )


# --- Stage 1: identity resolution of a referral ---------------------------------------------------


class IdentityResolutionStage:
    """Stage 1 (spec: "Identity resolves three ways"): the cohort's mint / exact-match / quarantine
    referrals, resolved the same way `demo2_identity_matcher.py` resolves its own fixture cases."""

    name = "identity_resolution"

    def setup(self, ctx: DemoContext) -> None:
        del ctx

    def run(self, ctx: DemoContext) -> StageReceipt:
        variants = {variant["case"]: variant for variant in ctx.fixtures["referral_variants"]}
        assertions = 0

        mint = variants["mint"]
        decision = demo2.resolve(demo2._referral_of(mint), demo2._lookup_of(mint))
        _check(
            decision.evidence.rule_id == mint["expected_rule_id"],
            f"mint referral: expected rule_id {mint['expected_rule_id']!r}, got {decision.evidence.rule_id!r}",
        )
        assertions += 1

        exact = variants["exact_match"]
        decision = demo2.resolve(demo2._referral_of(exact), demo2._lookup_of(exact))
        _check(isinstance(decision, Match), f"exact_match referral: expected Match, got {type(decision).__name__}")
        _check(
            decision.person_id == exact["expected_person_id"],
            f"exact_match referral: expected person_id {exact['expected_person_id']!r}, got {decision.person_id!r}",
        )
        assertions += 2

        quarantine = variants["quarantine"]
        decision = demo2.resolve(demo2._referral_of(quarantine), demo2._lookup_of(quarantine))
        _check(
            isinstance(decision, Ambiguous),
            f"quarantine referral: expected Ambiguous, got {type(decision).__name__}",
        )
        _check(
            list(decision.candidates) == quarantine["expected_candidate_person_ids"],
            f"quarantine referral: expected candidates {quarantine['expected_candidate_person_ids']!r}, "
            f"got {list(decision.candidates)!r}",
        )
        assertions += 2

        return StageReceipt(self.name, assertion_count=assertions, subject_keys=(ctx.patient_key,))


# --- Stage 2: consent ingress from an export landing row -------------------------------------------


class ConsentIngressStage:
    """Stage 2 (spec: "Consent lands attributed"): the fixture consent export row, swept twice —
    the first sweep declares, the second sweep of the identical row changes nothing (D16).

    `communication_consent`'s catalog entry state is `unset` (`TRANSITIONS["communication_consent"]`)
    — the subject's genesis, which is nobody's export row (Customer.io only ever exports an actual
    opt-in/opt-out). Every other stage 2/3/4 subject type either mints implicitly (`coverage`) or
    is opened by an explicit command this walk already issues (`billing_episode`); consent has
    neither yet, so `setup` aligns the subject at `unset` directly, the same "genesis alignment"
    precedent `demo3_live_kanban_drag.py` uses to seed a subject before its first drag.
    """

    name = "consent_ingress"

    def setup(self, ctx: DemoContext) -> None:
        row = ctx.fixtures["consent_export_row"]
        client = ctx.api_client(CUSTOMERIO_WRITER_ID)
        try:
            # The ledger row this sweep actually declares against is keyed
            # `f"{subject_key}:{channel}"` (`declarer.ledger_subject_key`, the
            # consent-reconciliation grain), not the bare patient key — genesis alignment must
            # target the same composite key or the sweep's own declare finds no prior 'unset'
            # to build on and fails the catalog's genesis check.
            response = client.submit_command(
                RecordCommunicationConsentCommand(
                    subject_key=ledger_subject_key(row["subject_key"], row["channel"]),
                    channel=row["channel"],
                    to_state="unset",
                ),
                effective_at=datetime.fromisoformat(row["event_time"]),
            )
            _check(
                response.is_success,
                f"consent genesis alignment to 'unset' did not commit: {response.classification}",
            )
        finally:
            client.close()

    def _sweep(self, row: Mapping[str, Any], client: PulseCoreClient) -> Any:
        reader = ConsentRowReader(ConsentFixtureRowSource([row]), _InMemoryCursorStore())
        declarations = []
        row_errors = []
        for page in reader.batches():
            declarations.extend(declare_consent_rows(page.rows, client))
            row_errors.extend(page.errors)
            reader.commit()
        return build_run_receipt(declarations, row_errors)

    def run(self, ctx: DemoContext) -> StageReceipt:
        row = ctx.fixtures["consent_export_row"]
        client = ctx.api_client(CUSTOMERIO_WRITER_ID)
        try:
            first = self._sweep(row, client)
            _check(first.malformed == 0, f"consent row failed validation: {first.row_errors}")
            _check(first.declared == 1, f"first sweep expected 1 declared row, got {first.declared}")
            _check(first.rejected == 0, f"first sweep rejected {first.rejected} row(s)")

            second = self._sweep(row, client)
            _check(
                second.declared == 0 and second.replayed == 1,
                f"second sweep of the same row expected 0 declared / 1 replayed, "
                f"got declared={second.declared} replayed={second.replayed}",
            )
        finally:
            client.close()

        return StageReceipt(self.name, assertion_count=4, subject_keys=(row["subject_key"],))


# --- Stage 3: a signed board drag -------------------------------------------------------------------


class BoardDragStage:
    """Stage 3 (spec: "The board is a door with a lock"): a legal drag commits one event, an
    illegal drag is rejected with the catalog's reason, and a tampered signature is refused before
    any rule runs — driven directly at the ledger's in-process Twenty webhook route.

    Twenty's own board state is not read here — no live Twenty exists offline, and the board's
    agreement with the ledger is stage 5's job (spec: "Board, warehouse copy, and fold agree"),
    exercised over the same subject this stage commits.
    """

    name = "board_drag"

    def setup(self, ctx: DemoContext) -> None:
        del ctx

    def run(self, ctx: DemoContext) -> StageReceipt:
        record_id = f"demo5-board-{ctx.patient_key}"
        card = demo3.ProjectedRecord(
            record_id=record_id, fields={"canonicalPatientId": ctx.patient_key, "programCode": "demo5"}
        )
        genesis_state = sorted(INITIAL_STATES[demo3.SUBJECT_TYPE])[0]

        with ctx.webhook_client() as http_client:
            ledger = demo3.LedgerDeliverer(ctx.api_base_url, ctx.webhook_secret, client=http_client)
            assertions = 0

            genesis_updated_at = demo3._wire_timestamp(datetime.now(tz=UTC))
            genesis_payload = demo3._drag_payload(
                card, wire_state=demo3.encode_option_value(genesis_state), updated_at=genesis_updated_at
            )
            status, body = ledger.deliver(genesis_payload)
            _check(status == 200, f"genesis alignment expected 200, got {status}")
            _check(
                body.get("disposition") in ("committed", "replayed"),
                f"genesis alignment expected committed or replayed, got {body.get('disposition')!r}",
            )
            assertions += 2

            legal_target = demo3._legal_target(genesis_state)
            legal_updated_at = demo3._wire_timestamp(datetime.now(tz=UTC))
            legal_payload = demo3._drag_payload(
                card, wire_state=demo3.encode_option_value(legal_target), updated_at=legal_updated_at
            )
            status, body = ledger.deliver(legal_payload)
            _check(status == 200, f"legal drag expected 200, got {status}")
            _check(
                body.get("disposition") == "committed",
                f"legal drag expected disposition 'committed', got {body.get('disposition')!r}",
            )
            _check(body.get("event_id") is not None, "legal drag committed but carried no event id")
            assertions += 3

            illegal_target = demo3._illegal_target(legal_target)
            illegal_updated_at = demo3._wire_timestamp(datetime.now(tz=UTC))
            illegal_payload = demo3._drag_payload(
                card, wire_state=demo3.encode_option_value(illegal_target), updated_at=illegal_updated_at
            )
            status, body = ledger.deliver(illegal_payload)
            _check(status == 200, f"illegal drag expected 200 (a rejection receipt), got {status}")
            _check(
                body.get("disposition") == "rejected",
                f"illegal drag expected disposition 'rejected', got {body.get('disposition')!r}",
            )
            _check(bool(body.get("reason")), "illegal drag's rejection carried no catalog reason")
            _check("event_id" not in body, "a rejected drag carried an event id — something committed")
            assertions += 4

            tampered_body = json.dumps(legal_payload).encode()
            timestamp = str(int(time.time() * 1000))
            tamper_response = http_client.post(
                TWENTY_WEBHOOK_PATH,
                content=tampered_body,
                headers={
                    "PULSE-Timestamp": timestamp,
                    "PULSE-Signature": "0" * 64,
                    "PULSE-Nonce": uuid.uuid4().hex,
                    "Content-Type": "application/json",
                },
            )
            _check(
                tamper_response.status_code >= 400,
                f"a tampered signature expected a rejection status, got {tamper_response.status_code}",
            )
            assertions += 1

        return StageReceipt(self.name, assertion_count=assertions, subject_keys=(record_id,))


# --- Stage 4: a verdict declared from the mart read -------------------------------------------------


class VerdictDeclareStage:
    """Stage 4 (spec: "A verdict becomes state"): the fixture mart row is relayed the same way
    `demo4_billing_declare_back.py` relays a live mart row — the billing episode is opened, the
    positive verdict qualifies it, and an immediate rerun declares nothing new."""

    name = "verdict_declare"

    def setup(self, ctx: DemoContext) -> None:
        del ctx

    def _run_relay_pass(
        self, client: PulseCoreClient, cursor_store: _InMemoryCursorStore, row: Mapping[str, Any]
    ) -> Any:
        reader = MartReader(MartFixtureRowSource([row]), cursor_store)
        declarer = Declarer(
            client,
            subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
            transition_by_outcome=TRANSITION_BY_OUTCOME,
            watermarks=reader.watermarks,
        )
        return run_relay(reader, declarer)

    def run(self, ctx: DemoContext) -> StageReceipt:
        row = ctx.fixtures["verdict_mart_row"]
        subject_key = row["subject_id"]
        # The episode must be open at or before the fixture verdict's own `as_of` (the pinned
        # fixture is a fixed past instant, not "now") — the ledger orders genesis by
        # `effective_at`, so opening "now" would leave the subject nonexistent as of the verdict's
        # own effective time (`demo4_billing_declare_back.py`'s own `now`-shared-with-the-seed-row
        # pattern, restated here against a fixture whose timestamp is already pinned).
        opened_at = datetime.fromisoformat(row["as_of"])
        client = ctx.api_client(VERDICT_RELAY_WRITER_ID)
        try:
            open_response = client.submit_command(
                OpenBillingEpisodeCommand(subject_key=subject_key, month=opened_at.date().replace(day=1)),
                effective_at=opened_at,
            )
            _check(open_response.is_success, f"open_billing_episode did not commit: {open_response.classification}")

            cursor_store = _InMemoryCursorStore()
            receipt = self._run_relay_pass(client, cursor_store, row)
            _check(receipt.succeeded, f"first relay pass failed: {receipt.failure}")
            _check(receipt.transitioned == 1, f"expected 1 transitioned verdict, got {receipt.transitioned}")

            with ctx.pool.connection() as conn:
                state = state_of_record(conn, BILLING_EPISODE_SUBJECT_TYPE, subject_key)
            _check(state == "qualified", f"expected billing_episode {subject_key} at 'qualified', got {state!r}")

            rerun = self._run_relay_pass(client, cursor_store, row)
            _check(
                rerun.declared == 0 and rerun.transitioned == 0,
                "an immediate rerun declared or transitioned something new",
            )
        finally:
            client.close()

        return StageReceipt(self.name, assertion_count=4, subject_keys=(subject_key,))


# --- Stage 5: every window agrees with the ledger --------------------------------------------------

#: The subjects the producing stages (2-4) commit to the ledger. Identity resolution (stage 1) is a
#: pure decision over the fixture, never a ledger write (`demo2.resolve` commits nothing), so it
#: contributes no subject here. `enrollment`'s subject key is `ctx.patient_key`, not the board
#: record id `BoardDragStage` mints — `V1_BOARD_MAPPINGS`' `canonical_key_path` resolves the
#: webhook's committed events on `canonicalPatientId`, which is `patient_key` (`mapping.py`).
_WINDOW_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("communication_consent", None),
    ("enrollment", None),
    ("billing_episode", None),
)


def _touched_subjects(ctx: DemoContext) -> tuple[tuple[str, str], ...]:
    consent_row = ctx.fixtures["consent_export_row"]
    verdict_row = ctx.fixtures["verdict_mart_row"]
    return (
        # The row this stage's sweep actually declares against is keyed on the
        # consent-reconciliation grain (`declarer.ledger_subject_key`), not the bare patient key.
        ("communication_consent", ledger_subject_key(consent_row["subject_key"], consent_row["channel"])),
        ("enrollment", ctx.patient_key),
        ("billing_episode", verdict_row["subject_id"]),
    )


WindowTuple = tuple[str, str, str, str]


def _reduce(subject_type: str, subject_key: str, state: str, as_of: datetime) -> WindowTuple:
    """The shape every window compares on (design.md decision 6): `(subject_type, subject_key,
    state, as_of)`, `as_of` normalized to UTC ISO-8601 so a window built from a differently
    zoned timestamp still compares equal to one that means the same instant."""
    return (subject_type, subject_key, state, as_of.astimezone(UTC).isoformat())


def _check_window_agrees(
    *, stage: str, subject_key: str, window: str, ledger: WindowTuple, observed: WindowTuple | None
) -> None:
    """Compare one window's reduced tuple to the ledger's, failing on the first disagreeing field.

    Names the stage, the subject key, and the field — never a value (spec: "A failure message
    names position, not content"). `observed=None` (the window found no state at all) is itself a
    disagreement on every field, reported as `state`, the field a missing window most concretely
    lacks.
    """
    if observed is None:
        _check(False, f"[{stage}] window {window!r} for subject {subject_key!r}: no state at field 'state'")
        return
    for field_name, ledger_value, observed_value in zip(
        ("subject_type", "subject_key", "state", "as_of"), ledger, observed, strict=True
    ):
        _check(
            ledger_value == observed_value,
            f"[{stage}] window {window!r} disagrees with the ledger for subject {subject_key!r} at field "
            f"{field_name!r}",
        )


def _fold_envelopes(subject_type: str, subject_key: str, envelopes: Iterable[Mapping[str, Any]]) -> WindowTuple | None:
    """The independent-fold and warehouse windows share this: both start from a list of published
    envelopes (one from `subject_history`, one drained off the LocalStack queue) and both owe their
    state to the one ordering rule `pulse_ledger.fold` states once (design.md decision 6)."""
    folded_events = [
        FoldedEvent(
            event_id=uuid.UUID(envelope["event_id"]),
            to_state=state_borne_by(envelope["payload"]) or "",
            effective_at=datetime.fromisoformat(envelope["effective_at"]),
            recorded_at=datetime.fromisoformat(envelope["recorded_at"]),
            reverses_event_id=(uuid.UUID(envelope["reverses_event_id"]) if envelope.get("reverses_event_id") else None),
        )
        for envelope in envelopes
        if state_borne_by(envelope["payload"]) is not None or envelope.get("reverses_event_id")
    ]
    folded = fold_state(folded_events)
    if folded is None:
        return None
    return _reduce(subject_type, subject_key, folded.state, folded.effective_at)


def _ledger_window(conn: psycopg.Connection, subject_type: str, subject_key: str) -> WindowTuple | None:
    """The comparison target: the co-committed `current_state` row itself, not a re-derivation."""
    row = conn.execute(
        "SELECT state, effective_at FROM ledger.current_state WHERE subject_type = %s AND subject_key = %s",
        (subject_type, subject_key),
    ).fetchone()
    if row is None:
        return None
    state, effective_at = row
    return _reduce(subject_type, subject_key, state, effective_at)


def _fold_window(conn: psycopg.Connection, subject_type: str, subject_key: str) -> WindowTuple | None:
    """The independent fold: raw committed events, refolded through `pulse_ledger.fold` rather
    than trusted from `current_state` (design.md decision 6, `subject_history`'s own read route,
    task 1.3)."""
    return _fold_envelopes(subject_type, subject_key, subject_history(conn, subject_type, subject_key))


def _drain_landed_events(
    sqs: Any, queue_url: str, wanted: frozenset[tuple[str, str]], *, timeout: float
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Drain committed envelopes for `wanted` (subject_type, subject_key) pairs off the LocalStack
    queue `ledger-relay` publishes onto (design.md decision 6: "the LocalStack-landed events"),
    the same queue `demo1_ledger_core.py._wait_for_event` observes a single event on.

    Polls until `timeout` seconds pass or two consecutive long-polls come back empty, whichever is
    first — the relay is typically fast, so an idle queue after a full round trip means every event
    this walk committed has already landed. Never deletes a message (`demo1`'s own convention):
    this stage only inspects the queue, it does not consume it.
    """
    collected: dict[tuple[str, str], list[dict[str, Any]]] = {key: [] for key in wanted}
    deadline = time.monotonic() + timeout
    idle_polls = 0
    while time.monotonic() < deadline and idle_polls < 2:
        response = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=5, MaxNumberOfMessages=10)
        messages = response.get("Messages", [])
        if not messages:
            idle_polls += 1
            continue
        idle_polls = 0
        for message in messages:
            body = json.loads(message["Body"])
            detail = body.get("detail", body)
            key = (detail.get("subject_type"), detail.get("subject_key"))
            if key in collected:
                collected[key].append(detail)
    return collected


def _board_state(
    events: Iterable[Mapping[str, Any]],
    *,
    client: ProjectionRestClient,
    subject_key: str,
) -> WindowTuple | None:
    """Replay one enrollment subject's committed events through the real `twenty_projection.apply`
    core onto the board (offline double or live dev Twenty, whichever `client` speaks to), then
    read back what it wrote through the same client — the board window is the live projection's
    own write and read path exercised directly, not a stand-in for it (design.md decision 2:
    "which board client... swapped by how `DemoContext` is built, stage code never checks the
    mode" — `apply_event` and this read-back are exactly that stage code).

    Reversal events carry no `to_state` and `apply_event` only understands state-bearing envelopes
    (`_parse_envelope` requires `payload.to_state`), so they are skipped here the same way
    `pulse_ledger.fold` drops them from state — a correction changes which prior event survives,
    not which events get applied.
    """
    for envelope in events:
        if envelope.get("reverses_event_id"):
            continue
        apply_event(envelope, client=client, board=V1_BOARD)

    records = client.find_records(V1_BOARD.plural, {SUBJECT_COLUMN: subject_key})
    if len(records) != 1:
        return None
    record = records[0]
    if record.get(V1_BOARD.status_field) is None:
        return None
    # `encode_option_value` is `str.upper` for the enrollment vocabulary (no dots in its states —
    # `pulse_core.twenty_model.encode_option_value`'s own docstring), so `str.lower` inverts it.
    state = str(record[V1_BOARD.status_field]).lower()
    as_of = datetime.fromisoformat(record[V1_BOARD.as_of_field])
    return _reduce("enrollment", subject_key, state, as_of)


class WindowAgreementStage:
    """Stage 5 (spec: "Board, warehouse copy, and fold agree"): after the producing stages, every
    read surface a live consumer would use is reduced to `(subject_type, subject_key, state,
    as_of)` and compared to the ledger's own `current_state` row, failing on the first
    disagreement. The board window applies only to `enrollment` — the one v1 board
    (`V1_BOARD_MAPPINGS`) — `communication_consent` and `billing_episode` render on no board today,
    so only their fold and warehouse windows are checked; a subject type the catalog defines but
    Twenty does not render is not this stage's spec defect to invent a board for (design.md
    non-goals: "no new ledger behavior")."""

    name = "window_agreement"

    def setup(self, ctx: DemoContext) -> None:
        del ctx

    def run(self, ctx: DemoContext) -> StageReceipt:
        subjects = _touched_subjects(ctx)
        landed = ctx.warehouse_reader(frozenset(subjects))

        assertions = 0
        with ctx.pool.connection() as conn, ctx.board_client() as board:
            for subject_type, subject_key in subjects:
                ledger = _ledger_window(conn, subject_type, subject_key)
                _check(
                    ledger is not None,
                    f"[{self.name}] ledger current_state: no row at field 'state' for subject {subject_key!r}",
                )
                assertions += 1

                fold_tuple = _fold_window(conn, subject_type, subject_key)
                _check_window_agrees(
                    stage=self.name, subject_key=subject_key, window="fold", ledger=ledger, observed=fold_tuple
                )
                assertions += 1

                warehouse_tuple = _fold_envelopes(subject_type, subject_key, landed[(subject_type, subject_key)])
                _check_window_agrees(
                    stage=self.name,
                    subject_key=subject_key,
                    window="warehouse",
                    ledger=ledger,
                    observed=warehouse_tuple,
                )
                assertions += 1

                if subject_type == "enrollment":
                    events = subject_history(conn, subject_type, subject_key)
                    board_tuple = _board_state(events, client=board, subject_key=subject_key)
                    _check_window_agrees(
                        stage=self.name,
                        subject_key=subject_key,
                        window="board",
                        ledger=ledger,
                        observed=board_tuple,
                    )
                    assertions += 1

        return StageReceipt(self.name, assertion_count=assertions, subject_keys=tuple(key for _, key in subjects))


# --- Stage 6: the rebuild drill -----------------------------------------------------------------


class RebuildDrillStage:
    """Stage 6 (spec: "Destroy then rebuild is row-identical", task 3.1): the operator drill
    (`twenty_projection.rebuild`, task 2.3) run as this walk's own last stage — capture the
    enrollment scope's board row, delete the columns the projection owns (never the row —
    `rebuild.py`'s own "destroyed" definition), rerun the rebuild over the same scope, and assert
    the repainted row equals the row captured before the drill, field for field.

    Runs only against `enrollment`, the one v1 board (`V1_BOARD`) — the same restriction stage 5
    already states for its own board window; `communication_consent` and `billing_episode` render
    on no board to rebuild.
    """

    name = "rebuild_drill"

    def setup(self, ctx: DemoContext) -> None:
        del ctx

    def run(self, ctx: DemoContext) -> StageReceipt:
        assertions = 0
        with ctx.board_client() as board:
            captured = board.find_records(V1_BOARD.plural, {SUBJECT_COLUMN: ctx.patient_key})
            _check(
                len(captured) == 1,
                f"[{self.name}] expected exactly one board row for subject {ctx.patient_key!r} "
                f"before the drill, found {len(captured)}",
            )
            assertions += 1
            before = dict(captured[0])
            record_id = before.get("id")
            _check(isinstance(record_id, str) and bool(record_id), f"[{self.name}] captured board row carried no id")
            assertions += 1

            # "Destroyed" means the columns the projection owns — the subject's anchor row stays
            # (rebuild.py's module docstring); a full row delete would be a different subject.
            board.patch_record(
                V1_BOARD.plural,
                record_id,
                {V1_BOARD.status_field: None, V1_BOARD.as_of_field: None, V1_BOARD.watermark_field: None},
            )

            history = ctx.api_client(REBUILD_WRITER_ID)
            try:
                scope = parse_scope(f"{V1_BOARD.subject_type}:{ctx.patient_key}")
                receipt = run_projection_rebuild(scope, history=history, client=board, operator="demo5-end-to-end")
            finally:
                history.close()

            _check(
                receipt.rows_written == 1,
                f"[{self.name}] expected the drill to repaint one row for subject {ctx.patient_key!r}, "
                f"wrote {receipt.rows_written}",
            )
            assertions += 1
            _check(receipt.orphans == 0, f"[{self.name}] rebuild reported an orphan for a scope that had a row")
            assertions += 1

            after = board.find_records(V1_BOARD.plural, {SUBJECT_COLUMN: ctx.patient_key})
            _check(
                len(after) == 1,
                f"[{self.name}] expected exactly one board row for subject {ctx.patient_key!r} "
                f"after the drill, found {len(after)}",
            )
            assertions += 1
            repainted = after[0]
            for field_name in (
                SUBJECT_COLUMN,
                PROGRAM_COLUMN,
                V1_BOARD.status_field,
                V1_BOARD.as_of_field,
                V1_BOARD.watermark_field,
            ):
                _check(
                    repainted.get(field_name) == before.get(field_name),
                    f"[{self.name}] repainted row disagrees with the captured row at field {field_name!r}",
                )
                assertions += 1

        return StageReceipt(self.name, assertion_count=assertions, subject_keys=(ctx.patient_key,))


#: Stages 1-6 (tasks 2.1, 2.2, 3.1).
STAGES: tuple[Stage, ...] = (
    IdentityResolutionStage(),
    ConsentIngressStage(),
    BoardDragStage(),
    VerdictDeclareStage(),
    WindowAgreementStage(),
    RebuildDrillStage(),
)


# --- Entry point -------------------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=demo1.DEFAULT_COMPOSE_FILE,
        help=f"docker-compose file to bring the offline stack up from (default: {demo1.DEFAULT_COMPOSE_FILE})",
    )
    parser.add_argument(
        "--skip-compose-up",
        action="store_true",
        help="assume the LocalStack/Postgres stack is already running and skip `docker compose up`",
    )
    parser.add_argument(
        "--database-url",
        default=demo1.DEFAULT_DATABASE_URL,
        help="ledger Postgres DSN, a plain postgresql:// URI (psycopg, not SQLAlchemy)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="run against the development ledger/board/warehouse instead of the offline stack "
        "(task 3.1's live context builder; every credential resolves from the environment only, "
        "see docs/runbooks/demo5-end-to-end.md)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    print("=== Demo 5: end to end ===")
    if args.live:
        try:
            config = resolve_live_config(os.environ)
        except LiveStartupError as error:
            print(f"FAILED: {error}", file=sys.stderr)
            return 1
        ctx = build_live_context(config)
    else:
        ctx = build_offline_context(
            compose_file=args.compose_file,
            database_url=args.database_url,
            skip_compose_up=args.skip_compose_up,
        )
    try:
        receipts = run_walk(STAGES, ctx)
    except StageFailure as exc:
        print(f"\nFAILED at stage {exc.stage_name!r}: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        ctx.close()

    print_receipt(receipts)
    print("\n=== Demo 5: all stages passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
