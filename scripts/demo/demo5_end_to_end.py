#!/usr/bin/env python
"""Demo 5 — end to end (task 2.1): one synthetic patient crosses every seam PULSE owns.

Per `openspec/changes/pulse-demo-closeout/specs/end-to-end-demo/spec.md`: six stages, in order,
each asserting its outcome against the ledger before the next stage begins, stopping at the first
failed assertion. This module is the harness — the `Stage` protocol, `DemoContext`, the offline
context builder, and the receipt printer — plus stages 1-4, composed from the demos and packages
that already own each door rather than reimplemented here (design.md decision 1: "compose, do not
rewrite"). Stage 5 (every window agrees) and stage 6 (the rebuild drill) land in later tasks
(2.2, 3.1) and are appended to `STAGES` there.

Per the roadmap's demo convention, this script needs the local LocalStack + Postgres compose stack
(`packages/ocean/infra/docker-compose.yml`) and stays out of `task check` — only
`tests/test_demo5_end_to_end.py`'s smoke-parse and harness-unit tests run there.

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

**The in-process board route** (offline context builder): `pulse_ledger.api.create_app` built
against the compose stack's own `ledger-postgres`, served over `starlette.testclient.TestClient`'s
synchronous ASGI transport rather than a live process — no port, no live Twenty, same route code
the deployed service runs.

Usage:
    scripts/demo/demo5_end_to_end.py [--skip-compose-up] [--database-url URL]
    scripts/demo/demo5_end_to_end.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
from consent_ingress.declarer import CUSTOMERIO_WRITER_ID, build_run_receipt, declare_consent_rows  # noqa: E402
from consent_ingress.row_source import ConsentRowReader  # noqa: E402
from consent_ingress.row_source import FixtureRowSource as ConsentFixtureRowSource  # noqa: E402
from identity.matcher import Ambiguous, Match  # noqa: E402
from pulse_core.client import PulseCoreClient  # noqa: E402
from pulse_core.generated import OpenBillingEpisodeCommand, RecordCommunicationConsentCommand  # noqa: E402
from pulse_ledger.api import TWENTY_WEBHOOK_PATH, create_app  # noqa: E402
from pulse_ledger.api_server import (  # noqa: E402
    build_committer,
    build_cursor_reader,
    build_cursor_writer,
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
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT, TRANSITION_BY_OUTCOME  # noqa: E402
from verdict_relay.declarer import Declarer  # noqa: E402
from verdict_relay.mart_reader import FixtureRowSource as MartFixtureRowSource  # noqa: E402
from verdict_relay.mart_reader import MartReader  # noqa: E402
from verdict_relay.production import WRITER_ID as VERDICT_RELAY_WRITER_ID  # noqa: E402
from verdict_relay.run import run_relay  # noqa: E402

#: Writer ids this walk needs credentials for. Not every stage's real production writer id is
#: registered — only the ones this demo's stages actually authenticate as.
WRITER_IDS = (CUSTOMERIO_WRITER_ID, VERDICT_RELAY_WRITER_ID)

BILLING_EPISODE_SUBJECT_TYPE = "billing_episode"


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
    board_transport: httpx.BaseTransport | None = None
    board_base_url: str = "http://demo5-board.local"
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

    def close(self) -> None:
        for closer in reversed(self._closers):
            closer()


def _make_registry(tokens: Mapping[str, str]) -> CredentialRegistry:
    """Build a `CredentialRegistry` directly from writer id -> token, bypassing the env-var suffix
    convention (`_writer_id_from_suffix` lowercases and maps `_` to `-`, which cannot round-trip a
    writer id like `customer.io`)."""
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
        board_transport=board_store.transport(),
        board_store=board_store,
    )
    ctx._closers.append(pool.close)
    ctx._closers.append(lambda: test_client.__exit__(None, None, None))
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
            response = client.submit_command(
                RecordCommunicationConsentCommand(
                    subject_key=row["subject_key"], channel=row["channel"], to_state="unset"
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
        ("communication_consent", consent_row["subject_key"]),
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
    transport: httpx.BaseTransport,
    base_url: str,
    store: _BoardDouble,
    subject_key: str,
) -> WindowTuple | None:
    """Replay one enrollment subject's committed events through the real `twenty_projection.apply`
    core onto the offline board double, then read back what it wrote — the board window is the
    live projection's own write path exercised in-process, not a stand-in for it (design.md
    decision 2: "which board client... swapped by how `DemoContext` is built, stage code never
    checks the mode" — `apply_event` is exactly that stage code).

    Reversal events carry no `to_state` and `apply_event` only understands state-bearing envelopes
    (`_parse_envelope` requires `payload.to_state`), so they are skipped here the same way
    `pulse_ledger.fold` drops them from state — a correction changes which prior event survives,
    not which events get applied.
    """
    client = ProjectionRestClient(base_url, token="demo5-board-window", transport=transport)  # noqa: S106
    try:
        for envelope in events:
            if envelope.get("reverses_event_id"):
                continue
            apply_event(envelope, client=client, board=V1_BOARD)
    finally:
        client.close()

    record = store.records.get(f"demo5-board-{subject_key}")
    if record is None or V1_BOARD.status_field not in record:
        return None
    # `encode_option_value` is `str.upper` for the enrollment vocabulary (no dots in its states —
    # `pulse_core.twenty_model.encode_option_value`'s own docstring), so `str.lower` inverts it.
    state = record[V1_BOARD.status_field].lower()
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
        sqs = demo1._sqs_client(ctx.aws_endpoint_url)
        queue_url = sqs.get_queue_url(QueueName=f"{ctx.event_bus_name}-{ctx.consumer}")["QueueUrl"]
        landed = _drain_landed_events(sqs, queue_url, frozenset(subjects), timeout=30.0)

        assertions = 0
        with ctx.pool.connection() as conn:
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
                    board_tuple = _board_state(
                        events,
                        transport=ctx.board_transport,
                        base_url=ctx.board_base_url,
                        store=ctx.board_store,
                        subject_key=subject_key,
                    )
                    _check_window_agrees(
                        stage=self.name,
                        subject_key=subject_key,
                        window="board",
                        ledger=ledger,
                        observed=board_tuple,
                    )
                    assertions += 1

        return StageReceipt(self.name, assertion_count=assertions, subject_keys=tuple(key for _, key in subjects))


#: Stages 1-5 (tasks 2.1, 2.2). Stage 6 (task 3.1) is appended once that task lands.
STAGES: tuple[Stage, ...] = (
    IdentityResolutionStage(),
    ConsentIngressStage(),
    BoardDragStage(),
    VerdictDeclareStage(),
    WindowAgreementStage(),
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
        "(live context builder lands in task 3.1; passing this flag today is a named refusal)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    print("=== Demo 5: end to end ===")
    if args.live:
        print("FAILED: --live is not yet implemented (task 3.1's live context builder)", file=sys.stderr)
        return 1

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
