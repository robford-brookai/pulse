"""The command API's runnable process (task 4.5's other half — `relay_worker.py` is the outbox leg).

Naming mirrors that split deliberately: `relay.py`/`relay_worker.py` is logic/process for the
outbox, `api.py`/`api_server.py` is logic/process for the command API. Run as
`python -m pulse_ledger.api_server`.

**DATABASE_URL is a plain `postgresql://` DSN.** `psycopg` v3 (unlike SQLAlchemy) does not
understand a `+driver` suffix — `relay_worker.py` already documents and depends on this. Alembic is
the one consumer that wants the `postgresql+psycopg://` form (`infra/postgres/env.py`); this module
and the relay both take the bare DSN. Getting the two crossed is a connect-time failure, not a
silent misconfiguration.

**Two committer paths, both wired.** `pulse_ledger.api.Committer` takes the idempotency key as
optional so a caller can omit it; when it is `None` here, the built committer falls through to
`pulse_ledger.commit.commit_declaration` rather than passing `None` on to
`pulse_ledger.idempotency.commit_idempotent`, whose `idempotency_key` is required (D16
accepted-if-present, ADR-0004/DNA-801). A command declared without a key still commits — it just
has no replay protection.

**A pool, not a shared connection.** `commit_declaration` holds a per-subject advisory lock for the
whole transaction (commit.py), and the route handlers are `async def`. One shared connection would
serialise every request in the process behind whichever subject's lock is held; a
`psycopg_pool.ConnectionPool` hands each request its own connection instead. The committer itself
still runs synchronously on the event loop thread — `async def` here buys FastAPI's request
handling, not concurrency inside one request. **A slow commit blocks the loop** for its duration;
acceptable at dev volume, and the fix when it stops being acceptable is `anyio.to_thread.run_sync`
around the call, not a rewrite of the commit path.

**Import-safe.** `uvicorn.run(create_app_from_env, factory=True)` means the environment is read
only when uvicorn calls the factory, never at import time — so this module imports cleanly, and
`tests/test_api_server.py` exercises the wiring with a fake pool and no `DATABASE_URL`, the same
posture `pulse_ledger.api`'s own tests already take.

**The comment poster degrades, never blocks boot.** `PULSE_LEDGER_TWENTY_API_TOKEN` absent means no
`TwentyCommentClient` is built and `pulse_ledger.api.create_app` gets no `comment_poster` — a
rejection still produces its receipt (`api.py`'s `CommentAdapterNotConfiguredError` path), it just
logs that the comment could not be posted. A comment channel that isn't configured yet must never
be the reason the service fails to start.

**`GET /health` lives here, not in `api.py`.** Every route `create_app` installs is
credential-authenticated by design (D15) — that module's whole contract. Liveness has no business
behind a bearer token, so it is added to the app after `create_app` returns, and it does nothing but
answer: no `SELECT 1`, so a database blip does not fail a liveness probe and cycle the pod under it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from pulse_ledger.api import CommentPoster, Committer, CursorReader, CursorWriter, StateReader, create_app
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration
from pulse_ledger.cursor import WriterCursor, get_cursor, put_cursor
from pulse_ledger.idempotency import commit_idempotent
from pulse_ledger.reads import state_of_record
from pulse_ledger.twenty.client import TWENTY_API_TOKEN_ENV, TwentyCommentClient

logger = logging.getLogger(__name__)

#: Where the Twenty comment adapter posts, when it is wired at all. Not read anywhere else — the
#: webhook route's own credential (`PULSE_LEDGER_TWENTY_WEBHOOK_SECRET*`) has no URL of its own to
#: agree with, since Twenty is the caller on that leg and the callee on this one.
TWENTY_BASE_URL_ENV = "PULSE_LEDGER_TWENTY_BASE_URL"

#: uvicorn defaults, overridable the same way every other piece of this wiring is: an env var, read
#: only inside the factory.
HOST_ENV = "PULSE_LEDGER_API_HOST"
PORT_ENV = "PULSE_LEDGER_API_PORT"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 — the container's bind address, not a leaked default
DEFAULT_PORT = 8000

#: Pool sizing. A command handler holds its connection for one commit's transaction, not the
#: request's lifetime beyond that, so this bounds concurrent in-flight commits rather than
#: concurrent requests.
DEFAULT_MIN_POOL_SIZE = 1
DEFAULT_MAX_POOL_SIZE = 10


def build_committer(pool: ConnectionPool) -> Committer:
    """The `Committer` the running service wires in: keyed commits replay, keyless ones do not.

    `commit_idempotent`'s `idempotency_key` is required, so a `None` here is routed to
    `commit_declaration` instead of being passed through — the fallthrough the module docstring
    promises (D16 accepted-if-present).
    """

    def committer(declaration: Declaration, idempotency_key: str | None) -> CommitResult:
        with pool.connection() as conn:
            if idempotency_key is None:
                return commit_declaration(conn, declaration)
            return commit_idempotent(conn, declaration, idempotency_key=idempotency_key)

    return committer


def build_cursor_reader(pool: ConnectionPool) -> CursorReader:
    def read_cursor(writer_id: str) -> WriterCursor | None:
        with pool.connection() as conn:
            return get_cursor(conn, writer_id)

    return read_cursor


def build_cursor_writer(pool: ConnectionPool) -> CursorWriter:
    def write_cursor(writer_id: str, cursor: Mapping[str, object]) -> WriterCursor:
        with pool.connection() as conn:
            return put_cursor(conn, writer_id, dict(cursor))

    return write_cursor


def build_state_reader(pool: ConnectionPool) -> StateReader:
    """The webhook route's state-of-record read, on a pooled connection per call.

    What makes echo suppression (twenty-projection design decision 5) real in the running
    service: without it a heal-back write's own webhook maps like a drag and the catalog posts a
    rejection note per heal.
    """

    def read_state(subject_type: str, subject_key: str) -> str | None:
        with pool.connection() as conn:
            return state_of_record(conn, subject_type, subject_key)

    return read_state


def build_comment_poster(environ: Mapping[str, str]) -> CommentPoster | None:
    """A `TwentyCommentClient` wired to `create_comment`, or `None` if its token is unset.

    Absence is not an error here (unlike `TwentyCommentClient.from_env`, which raises for an
    enabled-but-misconfigured adapter): this is the one call site that decides *whether* to build
    the adapter at all, so an absent token means "rejections still receipt, just without a
    posted comment" rather than a boot failure.
    """
    if not environ.get(TWENTY_API_TOKEN_ENV, "").strip():
        return None
    base_url = environ.get(TWENTY_BASE_URL_ENV)
    if not base_url:
        logger.warning(
            "%s is set but %s is not; the Twenty comment adapter cannot be built",
            TWENTY_API_TOKEN_ENV,
            TWENTY_BASE_URL_ENV,
        )
        return None
    client = TwentyCommentClient.from_env(environ, base_url=base_url)
    return client.create_comment


def _install_health_route(app: FastAPI) -> None:
    """Liveness only. No credential, no query — see the module docstring for why it lives here."""

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}


def _close_pool_on_shutdown(app: FastAPI, pool: ConnectionPool) -> None:
    """Wrap whatever lifespan `create_app` gave the app so the pool closes on shutdown too.

    `FastAPI.add_event_handler("shutdown", ...)` is gone in this FastAPI generation — lifespan
    context managers are the only hook left — so this wraps the app's existing (default, no-op)
    lifespan rather than replacing it, in case `create_app` ever grows one of its own.
    """
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Mapping[str, object] | None]:
        async with original_lifespan(app) as state:
            try:
                yield state
            finally:
                pool.close()

    # Starlette types this attribute as one of two exact lifespan-callable shapes; a wrapper
    # around whichever one the app already has cannot be typed as narrowly as either.
    app.router.lifespan_context = lifespan  # type: ignore[assignment]


def create_app_from_env(environ: Mapping[str, str] | None = None) -> FastAPI:
    """Build the running service's app: a real pool, both committer paths, `/health`.

    Reads `DATABASE_URL` (and the Twenty/host/port variables) from `environ` — `os.environ` if not
    given — so this is the one function in this module that touches the environment, and it is
    never called at import time (`create_app_from_env` is only invoked by uvicorn's factory, or by
    a test that passes its own `environ`).
    """
    env = os.environ if environ is None else environ
    pool = ConnectionPool(
        env["DATABASE_URL"],
        min_size=DEFAULT_MIN_POOL_SIZE,
        max_size=DEFAULT_MAX_POOL_SIZE,
    )
    app = create_app(
        committer=build_committer(pool),
        cursor_reader=build_cursor_reader(pool),
        cursor_writer=build_cursor_writer(pool),
        comment_poster=build_comment_poster(env),
        state_reader=build_state_reader(pool),
        environ=env,
    )
    _close_pool_on_shutdown(app, pool)
    _install_health_route(app)
    return app


def main() -> None:  # pragma: no cover — process entrypoint, exercised by running the container
    # Imported here, not at module scope: uvicorn lives in the `serve` extra
    # (`pyproject.toml`), not pulse-ledger's hard dependencies, so importing this module for its
    # wiring functions — as `tests/test_api_server.py` and the Docker relay command both do —
    # never requires an ASGI server to be installed.
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app_from_env,
        factory=True,
        host=os.environ.get(HOST_ENV, DEFAULT_HOST),
        port=int(os.environ.get(PORT_ENV, str(DEFAULT_PORT))),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
