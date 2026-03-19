"""mongodb-connector FastAPI app — lifespan, health, and CDC watcher bootstrap."""
from __future__ import annotations

import asyncio
import os
import signal
from contextlib import asynccontextmanager

import motor.motor_asyncio
import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.publisher import EventPublisher
from src.resume_token import ResumeTokenStore
from src.transformer import TRANSFORMER_REGISTRY
from src.watcher_manager import WatcherManager

logger = structlog.get_logger(__name__)


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
        raise ValueError(
            f"WATCH_COLLECTIONS contains unknown collection(s): {sorted(unknown)}"
        )

    # ---- Motor (MongoDB) ----
    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(mongodb_uri)
    db = mongo_client[mongodb_database]

    # ---- SQLAlchemy (Postgres) ----
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ---- components ----
    publisher = EventPublisher()
    token_store = ResumeTokenStore()
    shutdown_event = asyncio.Event()

    manager = WatcherManager(
        db=db,
        publisher=publisher,
        token_store=token_store,
        db_session_factory=session_factory,
        transformer_registry=TRANSFORMER_REGISTRY,
        collections=collections_list,
    )

    # ---- start all watchers ----
    await manager.start(shutdown_event)
    logger.info("mongodb_connector_started", collections=collections_list)

    # ---- SIGTERM handler ----
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)

    yield

    # ---- graceful shutdown ----
    shutdown_event.set()
    await manager.stop()
    publisher.close()
    mongo_client.close()
    await engine.dispose()
    logger.info("mongodb_connector_stopped")


app = FastAPI(title="mongodb-connector", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "service": "mongodb-connector"}
