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

The commit path is injected rather than imported-and-called: this module never opens a
transaction, and the service entrypoint (task 4.5) supplies the connection. That is also what lets
the auth boundary be tested without a database.

The Twenty webhook route (D8) is HMAC-signed rather than bearer-authenticated, and it ships
disabled — S2's `twenty-kanban-webhook-ingress` turns it on. Present-but-off is deliberate: the
middleware and the freshness window get written and tested now, when there is nothing behind the
door, rather than in the change that also has to make drag-to-command work.

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
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pulse_core.cursor import CURSOR_PATH_TEMPLATE, InvalidCursorError, validate_cursor

from pulse_ledger.auth import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    ActorSpoofError,
    AuthenticationError,
    CredentialRegistry,
    TwentyWebhookConfig,
    Writer,
    bearer_token,
    verify_signature,
)
from pulse_ledger.commit import CommitResult, Declaration, DeclarationError
from pulse_ledger.cursor import WriterCursor
from pulse_ledger.validation import IllegalTransitionError

logger = logging.getLogger(__name__)

COMMANDS_PATH = "/commands"
TWENTY_WEBHOOK_PATH = "/webhooks/twenty"
WRITER_CURSOR_PATH = CURSOR_PATH_TEMPLATE

#: Injected by the service entrypoint; a fake in tests. Anything that turns one declaration into
#: one commit result, including opening and owning the transaction.
Committer = Callable[[Declaration], CommitResult]

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


class NoCursorError(LookupError):
    """`GET /writers/{writer_id}/cursor` for a writer that has never checkpointed one. Maps to 404."""

    def __init__(self, writer_id: str) -> None:
        self.writer_id = writer_id
        super().__init__(f"no cursor persisted for writer {writer_id!r}")


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
    return Declaration.from_mapping(coerce_declaration_fields(attributed))


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
    }


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


def create_app(
    *,
    committer: Committer,
    registry: CredentialRegistry | None = None,
    twenty_webhook: TwentyWebhookConfig | None = None,
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
    """
    env = os.environ if environ is None else environ
    credentials = CredentialRegistry.from_env(env) if registry is None else registry
    webhook = TwentyWebhookConfig.from_env(env) if twenty_webhook is None else twenty_webhook
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
        declaration = declaration_from_request(body, writer)
        return _commit_response(committer(declaration))

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

    if webhook.enabled:
        secret = webhook.secret
        assert secret is not None  # noqa: S101 — TwentyWebhookConfig refuses enabled-without-secret

        @app.post(TWENTY_WEBHOOK_PATH, status_code=501)
        async def twenty_webhook_ingress(request: Request) -> Response:
            """D8's kanban ingress. Signed here; drag → command is S2's to write."""
            verify_signature(
                secret,
                await request.body(),
                request.headers.get(TIMESTAMP_HEADER),
                request.headers.get(SIGNATURE_HEADER),
                now=datetime.now(tz=timezone.utc),
            )
            return JSONResponse(
                status_code=501,
                content={"detail": "the Twenty kanban ingress is not implemented until S2"},
            )

    return app
