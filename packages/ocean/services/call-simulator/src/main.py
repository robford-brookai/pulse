"""call-simulator FastAPI app -- lifespan + consumer + health endpoint.

Consumes outreach approval events from ocean.ai-ops and simulates
call lifecycles, publishing events to the `interactions` domain on the OCEAN event bus.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.consumer import AIOConsumer
from src.publisher import build_publisher

__version__ = "1.0.0"

log = structlog.get_logger()

_consumer: AIOConsumer | None = None
_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer, _consumer_task

    brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    publisher = build_publisher()
    _consumer = AIOConsumer(bootstrap_servers=brokers, publisher=publisher)
    _consumer_task = asyncio.create_task(_consumer.start())

    log.info("call_simulator_started", brokers=brokers)
    yield

    if _consumer is not None:
        _consumer.stop()
    if _consumer_task is not None:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    log.info("call_simulator_stopped")


app = FastAPI(title="call-simulator", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "call-simulator"}
