"""hubspot-connector FastAPI app — lifespan, health, and webhook router."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.heartbeat import publish_heartbeat
from src.producer import RedpandaPublisher
from src.receiver import router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_servers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    publisher = RedpandaPublisher(bootstrap_servers=bootstrap_servers)
    app.state.publisher = publisher
    heartbeat_task = asyncio.create_task(publish_heartbeat(publisher, "hubspot-connector", "HubSpot Contact Lifecycle"))
    log.info("hubspot_connector_started", brokers=bootstrap_servers)

    yield

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await publisher.close()
    log.info("hubspot_connector_stopped")


app = FastAPI(title="hubspot-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "hubspot-connector"}
