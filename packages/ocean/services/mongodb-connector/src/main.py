"""mongodb-connector FastAPI app — lifespan, health, readiness, and CDC watcher bootstrap.

Leader election via Postgres advisory locks ensures only one replica
actively watches MongoDB collections.  Standby replicas poll the lock
every 5 seconds and promote automatically when the leader drops.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import motor.motor_asyncio
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ocean_broker import EventBridgePublisher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.leader import LeaderElector
from src.resume_token import ResumeTokenStore
from src.transformer import TRANSFORMER_REGISTRY
from src.watcher_manager import WatcherManager

logger = structlog.get_logger(__name__)

# How often a standby replica re-attempts leader acquisition.
_STANDBY_POLL_SECONDS = 5

# Maximum age (seconds) of the most recent resume-token update for
# the readiness probe to consider the system healthy.
_TOKEN_STALENESS_THRESHOLD = 60

# SQL to fetch the most recent resume-token update timestamp.
_LATEST_TOKEN_SQL = text("SELECT MAX(updated_at) FROM cdc_resume_tokens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- configuration from environment ----
    mongodb_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_database = os.environ.get("MONGODB_DATABASE", "brook")
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://localhost/ocean")

    _ALL_COLLECTIONS = ",".join(TRANSFORMER_REGISTRY.keys())
    watch_collections_raw = os.environ.get("WATCH_COLLECTIONS", _ALL_COLLECTIONS)
    collections_list = [c.strip() for c in watch_collections_raw.split(",") if c.strip()]

    # Validate against registry — fail fast on typos.
    unknown = set(collections_list) - set(TRANSFORMER_REGISTRY.keys())
    if unknown:
        raise ValueError(f"WATCH_COLLECTIONS contains unknown collection(s): {sorted(unknown)}")

    # ---- Motor (MongoDB) ----
    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(mongodb_uri)
    db = mongo_client[mongodb_database]

    # ---- SQLAlchemy (Postgres) ----
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ---- components ----
    # The connector's own Postgres session factory doubles as the publisher's dead-letter
    # sink: a publish the bus rejects lands in ``failed_webhooks`` instead of being dropped.
    publisher = EventBridgePublisher(db_session_maker=session_factory)
    token_store = ResumeTokenStore()
    shutdown_event = asyncio.Event()

    leader = LeaderElector(engine)

    manager = WatcherManager(
        db=db,
        publisher=publisher,
        token_store=token_store,
        db_session_factory=session_factory,
        transformer_registry=TRANSFORMER_REGISTRY,
        collections=collections_list,
    )

    # Expose state on app for probe endpoints.
    app.state.leader = leader
    app.state.manager = manager
    app.state.manager_started = False
    app.state.session_factory = session_factory

    # ---- SIGTERM handler ----
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)

    # ---- leader acquisition loop ----
    async def _leader_loop() -> None:
        """Poll for leader lock; start WatcherManager on acquisition."""
        while not shutdown_event.is_set():
            acquired = await leader.acquire()
            if acquired:
                await manager.start(shutdown_event)
                app.state.manager_started = True
                logger.info("mongodb_connector_started", collections=collections_list)
                return
            # Wait before retrying, but break early on shutdown.
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=_STANDBY_POLL_SECONDS,
                )
                # If we get here, shutdown was signalled while waiting.
                return
            except asyncio.TimeoutError:
                pass  # timeout expired — retry acquire

    await _leader_loop()

    yield

    # ---- graceful shutdown ----
    shutdown_event.set()
    if app.state.manager_started:
        await manager.stop()
    await leader.release()
    mongo_client.close()
    await engine.dispose()
    logger.info("mongodb_connector_stopped")


app = FastAPI(title="mongodb-connector", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness probe — always 200 if the process is alive."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness probe — 200 only when leader + watchers + fresh token."""
    _app = request.app
    is_leader = getattr(_app.state, "leader", None) is not None and _app.state.leader.is_leader
    watchers_started = getattr(_app.state, "manager_started", False)
    token_fresh = False

    # Check resume-token freshness against Postgres.
    if is_leader and watchers_started:
        session_factory = getattr(_app.state, "session_factory", None)
        if session_factory is not None:
            try:
                async with session_factory() as session:
                    result = await session.execute(_LATEST_TOKEN_SQL)
                    latest = result.scalar()
                    if latest is not None:
                        # Ensure timezone-aware comparison.
                        now = datetime.now(timezone.utc)
                        if latest.tzinfo is None:
                            age = (now - latest.replace(tzinfo=timezone.utc)).total_seconds()
                        else:
                            age = (now - latest).total_seconds()
                        token_fresh = age < _TOKEN_STALENESS_THRESHOLD
            except Exception as exc:
                logger.warning("readiness_token_check_failed", error=str(exc))

    checks = {
        "leader": is_leader,
        "watchers": watchers_started,
        "token_fresh": token_fresh,
    }

    ready = all(checks.values())

    if ready:
        logger.debug("readiness_check", ready=True, **checks)
        return JSONResponse(content={"ready": True}, status_code=200)
    else:
        logger.info("readiness_check", ready=False, **checks)
        return JSONResponse(
            content={"ready": False, "checks": checks},
            status_code=503,
        )
