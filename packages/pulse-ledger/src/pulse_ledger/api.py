"""The HTTP edge of the command API: authenticate, attribute, then hand to the commit path.

What this module is responsible for, and deliberately nothing else:

- **Authentication.** Every write carries a per-writer bearer credential (D15). No credential, an
  unreadable one, or one no writer owns, and the request never reaches the ledger.
- **Attribution.** The event's actor comes from the credential, and a body that tries to name an
  actor is rejected (`Writer.attribute`). This is the command-api spec's "a writer cannot spoof
  another actor" scenario, decided here because here is the only place both facts — who
  authenticated and what the body claims — are in the same scope.
- **Boundary coercion.** JSON has no datetimes and no UUIDs; `Declaration` has both. The strings
  are parsed here so nothing downstream has to wonder which it holds.
- **A rejection surface a client can act on.** 401 unauthenticated, 403 authenticated-but-not-that
  actor, 422 malformed or catalog-illegal — the last carrying the catalog's reason and version, as
  the spec requires.
- **Bulk backfill mode (task 3.5).** `POST /commands:batch` is the same boundary run once per item
  in an array, so the backfill loader authenticates once for a whole reconstructed sequence. The
  `backfill_genesis` and `reconstruction_gap` vocabulary is further restricted to the backfill
  actor here — the one place a command's declared type and its authenticated writer are both in
  scope, same reasoning as the spoof check above.

The commit path is injected rather than imported-and-called: this module never opens a
transaction, and the service entrypoint (task 4.5) supplies the connection. That is also what lets
the auth boundary be tested without a database.

The Twenty webhook route (D8) is HMAC-signed rather than bearer-authenticated, and it stays
env-disabled by default: enablement is a config event, per this change's migration plan. Enabled,
it verifies, hands the body to `pulse_ledger.twenty.mapping` (the interpretation lives there, not
here — design decision 1), and puts a mapped drag on the same committer as `/commands`. Its
attribution is a constant `Writer` for the webhook principal (decision 2), because the HMAC
authenticates Twenty and nothing in it proves which human dragged the card. Its responses are 200
with a disposition rather than a status vocabulary (decision 5): a webhook sender reads 2xx and
non-2xx, so a 4xx past the door buys a retry storm rather than a message anyone reads.

**Logging posture.** Auth failures log the writer id and the reason. They never log the
credential, the signature, or the request body — the body is the one thing here that will carry
PHI once C1 clears, and a rejection is precisely the moment code reaches for `logger.warning(...,
body)`. `Declaration` keeps `payload` and `evidence` out of its repr for the same reason.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pulse_core.cursor import CURSOR_PATH_TEMPLATE, InvalidCursorError, validate_cursor
from pulse_core.generated import BACKFILL_ONLY_COMMAND_TYPES

from pulse_ledger.auth import (
    BACKFILL_ACTOR_ID,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    ActorSpoofError,
    AuthenticationError,
    CredentialRegistry,
    TwentyWebhookConfig,
    Writer,
    bearer_token,
)
from pulse_ledger.commit import CommitResult, Declaration, DeclarationError
from pulse_ledger.cursor import WriterCursor
from pulse_ledger.twenty.mapping import (
    V1_BOARD_MAPPINGS,
    WEBHOOK_WRITER_ID,
    BoardMapping,
    Drag,
    MalformedPayloadError,
    NoOp,
    Unmapped,
    interpret,
)
from pulse_ledger.validation import IllegalTransitionError

logger = logging.getLogger(__name__)

COMMANDS_PATH = "/commands"
COMMANDS_BATCH_PATH = "/commands:batch"
TWENTY_WEBHOOK_PATH = "/webhooks/twenty"
WRITER_CURSOR_PATH = CURSOR_PATH_TEMPLATE

#: Injected by the service entrypoint; a fake in tests. Anything that turns one declaration and
#: its idempotency key (`None` when the body carried none) into one commit result, including
#: opening and owning the transaction — `pulse_ledger.idempotency.commit_idempotent` in the
#: running service.
Committer = Callable[[Declaration, "str | None"], CommitResult]

#: Injected the same way as `Committer` — a fake in tests, the real store (`pulse_ledger.cursor`)
#: in the running service. `CursorReader` mirrors `get_cursor`'s contract: `None` is "no cursor
#: yet", not an error.
CursorReader = Callable[[str], "WriterCursor | None"]
CursorWriter = Callable[[str, Mapping[str, object]], WriterCursor]


class CursorStoreNotConfiguredError(RuntimeError):
    """The app was built without a writer-cursor store wired in.

    Only raised if a cursor route is actually hit; an app that never uses `/writers/*/cursor`
    (every existing test fixture, until this task) never notices the default is unconfigured.
    """

    def __init__(self) -> None:
        super().__init__("no writer-cursor store is configured for this app")


def _unconfigured_cursor_reader(writer_id: str) -> WriterCursor | None:
    raise CursorStoreNotConfiguredError()


def _unconfigured_cursor_writer(writer_id: str, cursor: Mapping[str, object]) -> WriterCursor:
    raise CursorStoreNotConfiguredError()


_DECLARATION_FIELDS = frozenset(f.name for f in dataclasses.fields(Declaration))
_TIMESTAMP_FIELDS = ("effective_at", "occurred_at")
_UUID_FIELDS = ("correlation_id", "causation_id")


class UnknownDeclarationFieldError(DeclarationError):
    """A body carrying fields a declaration has no place for — refused, never silently dropped."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = names
        super().__init__(f"unknown declaration fields: {list(names)}")


class MalformedBodyError(DeclarationError):
    """A request body that is not a JSON object."""

    def __init__(self) -> None:
        super().__init__("the request body must be a JSON object")


class MalformedIdempotencyKeyError(DeclarationError):
    """An `idempotency_key` that is not a string — refused, never coerced or dropped."""

    def __init__(self) -> None:
        super().__init__("'idempotency_key' must be a string")


def split_idempotency_key(body: object) -> tuple[object, str | None]:
    """Carve `idempotency_key` out of the body before the unknown-field check sees it.

    The key addresses the commit, not the event — `Declaration` has no place for it, so it is
    extracted here rather than allow-listed in `coerce_declaration_fields`. Absence is fine: the
    key is accepted-if-present at this boundary, and a keyless body still commits (DNA-801).
    Non-dict bodies pass through untouched for `declaration_from_request` to reject.
    """
    if not isinstance(body, dict) or "idempotency_key" not in body:
        return body, None
    key = body["idempotency_key"]
    if not isinstance(key, str):
        raise MalformedIdempotencyKeyError()
    remainder = {name: value for name, value in body.items() if name != "idempotency_key"}
    return remainder, key


class NoCursorError(LookupError):
    """`GET /writers/{writer_id}/cursor` for a writer that has never checkpointed one. Maps to 404."""

    def __init__(self, writer_id: str) -> None:
        self.writer_id = writer_id
        super().__init__(f"no cursor persisted for writer {writer_id!r}")


class MalformedBatchBodyError(DeclarationError):
    """A `:batch` request body that is not a JSON array of commands."""

    def __init__(self) -> None:
        super().__init__("the request body must be a JSON array of commands")


class BackfillActorRequiredError(Exception):
    """A backfill-only event type declared by a writer other than the backfill actor.

    Maps to 403 — authenticated, but not the identity the command-api spec restricts this
    vocabulary to ("Backfill mode is the same path with a restricted vocabulary", task 3.5).
    """

    def __init__(self, event_type: str, writer_id: str) -> None:
        self.event_type = event_type
        self.writer_id = writer_id
        super().__init__(
            f"{event_type!r} may only be declared by the backfill actor {BACKFILL_ACTOR_ID!r}, not {writer_id!r}"
        )


class UnparseableTimestampError(DeclarationError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} must be an ISO-8601 timestamp")


class UnparseableUuidError(DeclarationError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} must be a UUID")


def _parse_timestamp(name: str, value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise UnparseableTimestampError(name)
    # `fromisoformat` learned the trailing Z in 3.11; the repo still tests 3.10.
    normalised = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise UnparseableTimestampError(name) from exc


def _parse_uuid(name: str, value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        raise UnparseableUuidError(name)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise UnparseableUuidError(name) from exc


def coerce_declaration_fields(body: Mapping[str, object]) -> dict[str, object]:
    """Turn a decoded JSON body into the types `Declaration` expects.

    Unknown fields are an error rather than an omission: a writer that misspells `subject_key`
    should hear about it, not commit an event without one.
    """
    unknown = tuple(
        sorted(set(body) - _DECLARATION_FIELDS - {"occurred_at", "rule_version", "recorded_at", "event_id"})
    )
    if unknown:
        raise UnknownDeclarationFieldError(unknown)
    coerced = dict(body)
    for name in _TIMESTAMP_FIELDS:
        if coerced.get(name) is not None:
            coerced[name] = _parse_timestamp(name, coerced[name])
    for name in _UUID_FIELDS:
        if coerced.get(name) is not None:
            coerced[name] = _parse_uuid(name, coerced[name])
    bounds = coerced.get("evidence_bounds")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        coerced["evidence_bounds"] = (
            _parse_timestamp("evidence_bounds[0]", bounds[0]),
            _parse_timestamp("evidence_bounds[1]", bounds[1]),
        )
    return coerced


def declaration_from_request(body: object, writer: Writer) -> Declaration:
    """The whole attribution boundary in one function: the body says what, the credential says who."""
    if not isinstance(body, dict):
        raise MalformedBodyError()
    attributed = writer.attribute(body)
    declaration = Declaration.from_mapping(coerce_declaration_fields(attributed))
    if declaration.event_type in BACKFILL_ONLY_COMMAND_TYPES and writer.writer_id != BACKFILL_ACTOR_ID:
        raise BackfillActorRequiredError(declaration.event_type, writer.writer_id)
    return declaration


def _commit_response(result: CommitResult) -> dict[str, object]:
    state = (
        None
        if result.state is None
        else {
            "state": result.state.state,
            "effective_at": result.state.effective_at,
            "recorded_at": result.state.recorded_at,
            "event_id": result.state.event_id,
        }
    )
    return {
        "event_id": result.event_id,
        "recorded_at": result.recorded_at,
        "rule_version": result.rule_version,
        "outbox_seq": result.outbox_seq,
        "state": state,
        "replayed": result.replayed,
    }


#: The disposition vocabulary of the Twenty webhook response and its log line (design decision 5).
#: Everything past the door is a 200 — Twenty classifies 2xx/non-2xx and retries the rest, so a
#: status code is a retry instruction, not a verdict. The verdict is this field.
DISPOSITION_COMMITTED = "committed"
DISPOSITION_REPLAYED = "replayed"
DISPOSITION_NOOP = "noop"
DISPOSITION_UNMAPPED = "unmapped"
#: Not in decision 5's list: a body that is not the shape Twenty documents. It cannot become valid
#: on redelivery, so it is acknowledged rather than retried forever, and the field path — never the
#: body — is what the response and the log line carry.
DISPOSITION_MALFORMED = "malformed"

#: The principal every webhook command commits as (design decision 2). Built from the same `Writer`
#: the bearer routes resolve to, so attribution and the spoof rule stay one implementation: the HMAC
#: authenticates *Twenty*, so the actor is this credential's principal and never a payload field.
WEBHOOK_WRITER = Writer(writer_id=WEBHOOK_WRITER_ID)


def _log_disposition(disposition: str, **facts: object) -> None:
    """One countable line per webhook delivery: route, disposition, and identifiers or codes only.

    Every value passed here must be an identifier, a state name, or a fixed code. Record *fields*
    are the one thing the webhook body carries that this process may not log (design Risks), so
    this helper takes named facts rather than an interpolated message — a caller reaching for
    `logger.info(..., payload)` has to go around it, visibly.
    """
    detail = " ".join(f"{name}={value}" for name, value in facts.items() if value is not None)
    logger.info("%s disposition=%s %s", TWENTY_WEBHOOK_PATH, disposition, detail)


def _webhook_commit_response(drag: Drag, committer: Committer) -> dict[str, object]:
    """Attribute the mapped drag to the webhook principal and put it on the single write path."""
    declaration = Declaration.from_mapping(WEBHOOK_WRITER.attribute(drag.declaration_fields))
    result = committer(declaration, drag.idempotency_key)
    disposition = DISPOSITION_REPLAYED if result.replayed else DISPOSITION_COMMITTED
    _log_disposition(
        disposition,
        subject_type=declaration.subject_type,
        subject_key=declaration.subject_key,
        to_state=declaration.to_state,
        state=None if result.state is None else result.state.state,
    )
    return {"disposition": disposition, **_commit_response(result)}


def _twenty_webhook_disposition(
    body: bytes,
    mappings: Sequence[BoardMapping],
    committer: Committer,
) -> dict[str, object]:
    """Interpret one verified body and act on it — the whole route past `verify`.

    Split out of the handler so the handler is what it claims to be: verify, then this. Auth has
    already happened by the time anything here runs, which is the ordering the auth spec is about.
    """
    try:
        payload: Any = json.loads(body)
    except ValueError:
        _log_disposition(DISPOSITION_MALFORMED, field_path="<body>")
        return {"disposition": DISPOSITION_MALFORMED, "field_path": "<body>"}
    if not isinstance(payload, Mapping):
        _log_disposition(DISPOSITION_MALFORMED, field_path="<body>")
        return {"disposition": DISPOSITION_MALFORMED, "field_path": "<body>"}
    try:
        disposition = interpret(payload, mappings)
    except MalformedPayloadError as exc:
        _log_disposition(DISPOSITION_MALFORMED, field_path=exc.field_path)
        return {"disposition": DISPOSITION_MALFORMED, "field_path": exc.field_path}
    if isinstance(disposition, NoOp):
        _log_disposition(DISPOSITION_NOOP, reason=disposition.reason)
        return {"disposition": DISPOSITION_NOOP, "reason": disposition.reason}
    if isinstance(disposition, Unmapped):
        _log_disposition(
            DISPOSITION_UNMAPPED,
            record=str(disposition.record_ref),
            board=disposition.board,
        )
        return {
            "disposition": DISPOSITION_UNMAPPED,
            "record_ref": str(disposition.record_ref),
            "board": disposition.board,
        }
    return _webhook_commit_response(disposition, committer)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def _unauthenticated(request: Request, exc: Exception) -> Response:
        # No credential, no signature, no body — only the reason and the route.
        assert isinstance(exc, AuthenticationError)  # noqa: S101 — handler is registered for this type
        logger.warning("rejected unauthenticated request to %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": exc.challenge},
        )

    @app.exception_handler(ActorSpoofError)
    async def _spoofed(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, ActorSpoofError)  # noqa: S101 — handler is registered for this type
        logger.warning(
            "writer %s tried to declare %r from the body; rejected",
            exc.writer_id,
            exc.field,
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "message": str(exc),
                    "field": exc.field,
                    "writer_id": exc.writer_id,
                    "claimed": exc.claimed,
                }
            },
        )

    @app.exception_handler(BackfillActorRequiredError)
    async def _backfill_restricted(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, BackfillActorRequiredError)  # noqa: S101 — handler is registered for this type
        logger.warning(
            "writer %s attempted backfill-only event type %r; rejected",
            exc.writer_id,
            exc.event_type,
        )
        return JSONResponse(
            status_code=403,
            content={"detail": {"message": str(exc), "event_type": exc.event_type, "writer_id": exc.writer_id}},
        )

    @app.exception_handler(IllegalTransitionError)
    async def _illegal(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, IllegalTransitionError)  # noqa: S101 — handler is registered for this type
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "message": str(exc),
                    "reason": exc.reason,
                    "catalog_version": exc.catalog_version,
                    "subject_type": exc.subject_type,
                    "from_state": exc.from_state,
                    "to_state": exc.to_state,
                }
            },
        )

    @app.exception_handler(DeclarationError)
    async def _malformed(request: Request, exc: Exception) -> Response:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(InvalidCursorError)
    async def _invalid_cursor(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, InvalidCursorError)  # noqa: S101 — handler is registered for this type
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NoCursorError)
    async def _no_cursor(request: Request, exc: Exception) -> Response:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


def _cursor_response(cursor: WriterCursor) -> dict[str, object]:
    return {"writer_id": cursor.writer_id, "cursor": cursor.cursor, "updated_at": cursor.updated_at}


def _require_own_writer(writer: Writer, path_writer_id: str) -> None:
    """A writer may read or write only its own cursor — the same D15 rule as the command body's.

    Raises `ActorSpoofError` for the mismatch: an authenticated writer claiming an identity the
    credential disagrees with is exactly what that error already names, whether the claim arrives
    in a body field or a path segment.
    """
    if writer.writer_id != path_writer_id:
        raise ActorSpoofError("writer_id", writer.writer_id, path_writer_id)


def _install_cursor_routes(
    app: FastAPI,
    credentials: CredentialRegistry,
    read_cursor: CursorReader,
    write_cursor: CursorWriter,
) -> None:
    @app.get(WRITER_CURSOR_PATH)
    async def get_writer_cursor(writer_id: str, request: Request) -> dict[str, object]:
        writer = credentials.resolve(bearer_token(request.headers.get("Authorization")))
        _require_own_writer(writer, writer_id)
        stored = read_cursor(writer_id)
        if stored is None:
            raise NoCursorError(writer_id)
        return _cursor_response(stored)

    @app.put(WRITER_CURSOR_PATH, status_code=200)
    async def put_writer_cursor(writer_id: str, request: Request) -> dict[str, object]:
        writer = credentials.resolve(bearer_token(request.headers.get("Authorization")))
        _require_own_writer(writer, writer_id)
        try:
            body: Any = json.loads(await request.body())
        except ValueError as exc:
            raise MalformedBodyError() from exc
        if not isinstance(body, dict):
            raise MalformedBodyError()
        canonical = validate_cursor(body)
        stored = write_cursor(writer_id, canonical)
        return _cursor_response(stored)


def create_app(
    *,
    committer: Committer,
    registry: CredentialRegistry | None = None,
    twenty_webhook: TwentyWebhookConfig | None = None,
    board_mappings: Sequence[BoardMapping] | None = None,
    environ: Mapping[str, str] | None = None,
    cursor_reader: CursorReader | None = None,
    cursor_writer: CursorWriter | None = None,
) -> FastAPI:
    """Build the command API.

    Credentials and the webhook switch come from the environment unless passed in. A service with
    no writer credentials cannot serve anyone, so `CredentialRegistry.from_env` refuses to build
    one — the app fails to boot rather than starting with an open or useless door.

    `cursor_reader`/`cursor_writer` are injected the same way `committer` is (a fake in tests, the
    real store in the running service) and default to a stub that raises only if a cursor route is
    actually hit, so building an app for command-path tests alone needs no database either.

    `board_mappings` is the Twenty kanban wiring (design decision 3): which object and status field
    project which subject. It defaults to `V1_BOARD_MAPPINGS` — the one board this service is
    configured for — and only matters when the webhook route is enabled.
    """
    env = os.environ if environ is None else environ
    credentials = CredentialRegistry.from_env(env) if registry is None else registry
    webhook = TwentyWebhookConfig.from_env(env) if twenty_webhook is None else twenty_webhook
    mappings = V1_BOARD_MAPPINGS if board_mappings is None else board_mappings
    read_cursor = _unconfigured_cursor_reader if cursor_reader is None else cursor_reader
    write_cursor = _unconfigured_cursor_writer if cursor_writer is None else cursor_writer

    app = FastAPI(title="PULSE ledger command API", version="0.1.0")
    _install_error_handlers(app)

    @app.post(COMMANDS_PATH, status_code=201)
    async def submit_command(request: Request) -> dict[str, object]:
        writer = credentials.resolve(bearer_token(request.headers.get("Authorization")))
        try:
            body: Any = json.loads(await request.body())
        except ValueError as exc:
            raise MalformedBodyError() from exc
        body, idempotency_key = split_idempotency_key(body)
        declaration = declaration_from_request(body, writer)
        return _commit_response(committer(declaration, idempotency_key))

    _install_cursor_routes(app, credentials, read_cursor, write_cursor)

    @app.post(COMMANDS_BATCH_PATH, status_code=201)
    async def submit_command_batch(request: Request) -> list[dict[str, object]]:
        """Bulk backfill mode: one bearer credential, one array of commands, same validation.

        Every item runs through the same `declaration_from_request` boundary as `/commands` — the
        same catalog legality, the same attribution, and the same backfill-actor restriction — so
        the batch is "the same endpoint family" the spec requires rather than a second write path.
        Declarations are built for the whole array before any of them commits: a malformed or
        spoofed item further down the array aborts the batch before its predecessors are attempted.
        Once committing starts, each item is its own call to `committer` (its own transaction, as
        `/commands` already is) — the array is a convenience for the backfill loader's single
        credential, not an atomic unit across items.
        """
        writer = credentials.resolve(bearer_token(request.headers.get("Authorization")))
        try:
            body: Any = json.loads(await request.body())
        except ValueError as exc:
            raise MalformedBodyError() from exc
        if not isinstance(body, list):
            raise MalformedBatchBodyError()
        split = [split_idempotency_key(item) for item in body]
        declarations = [(declaration_from_request(item, writer), key) for item, key in split]
        return [_commit_response(committer(declaration, key)) for declaration, key in declarations]

    if webhook.enabled:

        @app.post(TWENTY_WEBHOOK_PATH, status_code=200)
        async def twenty_webhook_ingress(request: Request) -> dict[str, object]:
            """D8's kanban ingress: verify, interpret, commit.

            The body is read and verified before it is parsed — nothing this route does can run
            ahead of the signature check, which is the whole of the auth spec's "before any
            processing". `webhook.verify` accepts either configured secret, so a D15 rotation
            window rejects nothing that Twenty signed correctly.

            An `IllegalTransitionError` from the committer still reaches the app's 422 handler:
            the rejection receipt and the card comment are task 3.2's, and turning that into a
            200 `rejected` disposition before the receipt exists would only hide it.
            """
            body = await request.body()
            webhook.verify(
                body,
                request.headers.get(TIMESTAMP_HEADER),
                request.headers.get(SIGNATURE_HEADER),
                now=datetime.now(tz=timezone.utc),
            )
            return _twenty_webhook_disposition(body, mappings, committer)

    return app
