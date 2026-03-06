"""event-store FastAPI app — /health endpoint and consumer background task."""
from __future__ import annotations

import asyncio
import os

import structlog
import uvicorn
from fastapi import FastAPI

from src import consumer, writer

log = structlog.get_logger()

app = FastAPI(title="event-store", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "event-store", "version": "0.1.0"}


@app.on_event("startup")
async def startup() -> None:
    bootstrap_servers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    log.info("starting_consumer", brokers=bootstrap_servers)
    asyncio.create_task(consumer.run_consumer(writer, bootstrap_servers))


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000)
