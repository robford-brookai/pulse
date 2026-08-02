# AUDIT-04 GATE: Anthropic HIPAA BAA must be confirmed before deploying to production.
# This service is safe to build and test locally. Production deploy is blocked until BAA is in place.
# Track BAA status: [link to Linear/Notion issue]
"""slack-bot FastAPI app — health endpoint, Slack bolt integration, background tasks."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = structlog.get_logger()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
OPS_SLACK_CHANNEL = os.environ.get("OPS_SLACK_CHANNEL", "#care-alerts-ops")
HASURA_URL = os.environ.get("HASURA_URL", "http://localhost:8090")
REDPANDA_BROKERS = os.environ.get("REDPANDA_BROKERS", "localhost:9092")


class MCPApiKeyMiddleware(BaseHTTPMiddleware):
    """Enforce X-Api-Key header on all /mcp requests."""

    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/mcp"):
            api_key = request.headers.get("X-Api-Key", "")
            expected = os.environ.get("MCP_API_KEY", "")
            if not expected or api_key != expected:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("slack_bot_starting")

    engine = None
    session_maker = None

    if DATABASE_URL:
        engine = create_async_engine(DATABASE_URL, echo=False)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
    else:
        log.warning("DATABASE_URL_not_set_skipping_db")

    if not SLACK_BOT_TOKEN:
        log.warning("SLACK_BOT_TOKEN_not_set_skipping_consumers_and_poller")
        yield
        if engine:
            await engine.dispose()
        log.info("slack_bot_stopped")
        return

    from slack_sdk.web.async_client import AsyncWebClient

    from src import consumer as consumer_module
    from src.bolt_app import bolt_handler, set_hasura_secret, set_publisher, set_session_maker
    from src.health_poller import poll_connector_health
    from src.publisher import RedpandaPublisher
    from src.slash_commands import set_slash_deps
    from src.thread_manager import ThreadManager

    slack_client = AsyncWebClient(token=SLACK_BOT_TOKEN)

    # Validate Slack token at startup (Phase 15)
    try:
        auth_response = await slack_client.auth_test()
        log.info("slack_connected", workspace=auth_response["team"], bot=auth_response["user"])
    except Exception:
        log.warning("slack_not_configured_headless_mode")

    # Wire bolt_app dependencies (BUG 2 fix)
    if session_maker is not None:
        set_session_maker(session_maker)
    publisher = RedpandaPublisher(REDPANDA_BROKERS)
    set_publisher(publisher)

    hasura_secret = os.environ.get("HASURA_GRAPHQL_ADMIN_SECRET", "")
    if hasura_secret:
        set_hasura_secret(hasura_secret)

    # Wire slash command dependencies (Phase 15 Plan 04)
    set_slash_deps(HASURA_URL, hasura_secret)

    # Wire MCP server dependencies (Phase 15 Plan 03)
    from src.mcp_server import set_mcp_deps

    set_mcp_deps(slack_client, session_maker, publisher, HASURA_URL, hasura_secret)

    # Create ThreadManager for thread tracking (Phase 15)
    thread_manager = ThreadManager(slack_client, session_maker)

    async def _slack_events_endpoint(request: Request) -> Response:
        return await bolt_handler.handle(request)

    app.add_api_route("/slack/events", _slack_events_endpoint, methods=["POST"])

    consumer_task = asyncio.create_task(
        consumer_module.run_consumer(
            slack_client,
            session_maker,
            REDPANDA_BROKERS,
            HASURA_URL,
            publisher=publisher,
            thread_manager=thread_manager,
        )
    )
    poller_task = asyncio.create_task(poll_connector_health(slack_client, OPS_SLACK_CHANNEL, session_maker))

    log.info("slack_bot_started", brokers=REDPANDA_BROKERS, ops_channel=OPS_SLACK_CHANNEL)
    yield

    consumer_task.cancel()
    poller_task.cancel()
    try:
        await asyncio.gather(consumer_task, poller_task, return_exceptions=True)
    except Exception:
        pass

    if engine:
        await engine.dispose()
    log.info("slack_bot_stopped")


app = FastAPI(title="slack-bot", version="0.1.0", lifespan=lifespan)

# Mount MCP server at /mcp (Phase 15 Plan 03)
from src.mcp_server import create_mcp_app

app.mount("/mcp", create_mcp_app())
app.add_middleware(MCPApiKeyMiddleware)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "slack-bot", "version": "0.1.0"}
