"""hubspot-connector FastAPI app — lifespan, health, and webhook router."""

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
    # The publisher's failed_webhooks fallback needs a database. Without a session maker a bus
    # failure is logged and the event dropped, so the connector wires one rather than leaving it
    # optional — under Kafka this service accepted a session maker and was never given one.
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean")
    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_maker = session_maker

    publisher = EventBridgePublisher(db_session_maker=session_maker)
    app.state.publisher = publisher
    heartbeat_task = asyncio.create_task(publish_heartbeat(publisher, "hubspot-connector", "HubSpot Contact Lifecycle"))
    log.info("hubspot_connector_started", event_bus=os.environ.get("OCEAN_EVENT_BUS_NAME", "ocean"))

    yield

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    log.info("hubspot_connector_stopped")


app = FastAPI(title="hubspot-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "hubspot-connector"}
