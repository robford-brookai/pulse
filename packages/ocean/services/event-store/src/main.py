"""event-store FastAPI app — /health endpoint and consumer background task."""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from src import consumer, writer

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_servers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    log.info("starting_consumer", brokers=bootstrap_servers)
    task = asyncio.create_task(consumer.run_consumer(writer, bootstrap_servers))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        log.info("consumer_stopped")


app = FastAPI(title="event-store", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "event-store", "version": "0.1.0"}


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000)
