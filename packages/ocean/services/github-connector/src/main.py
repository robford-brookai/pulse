"""github-connector FastAPI app — lifespan, health, and webhook router."""

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
    # The session maker is what makes the publisher's failed_webhooks fallback real rather than
    # nominal: without one, EventBridgePublisher logs a failed publish and drops the event.
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean")
    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_maker = session_maker

    publisher = EventBridgePublisher(db_session_maker=session_maker)
    app.state.publisher = publisher
    heartbeat_task = asyncio.create_task(publish_heartbeat(publisher, "github-connector", "GitHub PR/Commit Signals"))
    log.info("github_connector_started", event_bus=os.environ.get("OCEAN_EVENT_BUS_NAME", "ocean"))

    yield

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    # No publisher close: EventBridge PutEvents is a request per publish, so there is no producer
    # queue left to flush the way the Redpanda AIOProducer needed.
    await engine.dispose()
    log.info("github_connector_stopped")


app = FastAPI(title="github-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "github-connector"}
