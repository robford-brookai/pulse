"""zcc-connector FastAPI app — lifespan, health, and webhook router."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.heartbeat import publish_heartbeat
from src.producer import build_publisher
from src.receiver import router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    publisher = build_publisher()
    app.state.publisher = publisher
    heartbeat_task = asyncio.create_task(publish_heartbeat(publisher, "zcc-connector", "Zoom Contact Center"))
    log.info("zcc_connector_started")

    yield

    # Shutdown. The publisher needs no close: EventBridge PutEvents is a request per call, so
    # there is no producer queue to flush the way the Kafka client had.
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    log.info("zcc_connector_stopped")


app = FastAPI(title="zcc-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "zcc-connector"}
