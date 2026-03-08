"""agent-worker FastAPI app -- lifespan + /health endpoint.

Loads personas from AGENTS.md, creates publisher, starts consumer
as a background task.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.consumer import run_consumer
from src.personas import load_personas
from src.publisher import RedpandaPublisher

__version__ = "0.1.0"

log = structlog.get_logger()

_publisher: RedpandaPublisher | None = None
_consumer_task: asyncio.Task | None = None
_claimed_tasks: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _publisher, _consumer_task

    brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    agents_path = os.environ.get("AGENTS_MD_PATH", "/app/agents.md")
    compression = float(os.environ.get("COMPRESSION_RATIO", "960"))

    _publisher = RedpandaPublisher(bootstrap_servers=brokers)
    personas = load_personas(agents_path)
    log.info(
        "agent_worker_started",
        brokers=brokers,
        personas=[p.id for p in personas],
        compression_ratio=compression,
    )

    _consumer_task = asyncio.create_task(
        run_consumer(personas, brokers, _publisher, _claimed_tasks)
    )

    yield

    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    log.info("agent_worker_stopped")


app = FastAPI(title="agent-worker", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent-worker"}
