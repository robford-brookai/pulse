"""pocar-connector FastAPI app — lifespan, health, and webhook router."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from ocean_broker import EventBridgePublisher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.heartbeat import publish_heartbeat
from src.receiver import router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean")
    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_maker = session_maker

    # Region and bus name come from the environment inside the publisher, so the service names
    # neither. Handing it the session maker is what gives every publish site the failed_webhooks
    # fallback the connector used to implement itself.
    publisher = EventBridgePublisher(db_session_maker=session_maker)
    app.state.publisher = publisher
    log.info("pocar_connector_started")

    heartbeat_task = asyncio.create_task(publish_heartbeat(publisher, "pocar-connector", "POCAR"))

    yield

    # Shutdown — cancel the heartbeat before tearing down its dependencies. The publisher holds
    # no broker connection to flush, so the engine is the only thing left to close.
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()
    log.info("pocar_connector_stopped")


app = FastAPI(title="pocar-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "pocar-connector", "version": "0.1.0"}
