"""agent-worker FastAPI app -- lifespan + /health endpoint.

Loads personas from AGENTS.md, starts consumer as a background task.
Publisher and consumer creation are deferred to the background task
so the FastAPI /health endpoint becomes responsive immediately.
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

_consumer_task: asyncio.Task | None = None
_claimed_tasks: set[str] = set()


async def _start_worker(brokers: str, personas, compression: float) -> None:
    """Initialize publisher and consumer in background.

    Runs after lifespan yields so /health is already responsive.
    """
    publisher = await asyncio.to_thread(RedpandaPublisher, bootstrap_servers=brokers)
    log.info(
        "agent_worker_started",
        brokers=brokers,
        personas=[p.id for p in personas],
        compression_ratio=compression,
    )
    await run_consumer(personas, brokers, publisher, _claimed_tasks)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task

    brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    agents_path = os.environ.get("AGENTS_MD_PATH", "/app/AGENTS.md")
    compression = float(os.environ.get("COMPRESSION_RATIO", "960"))

    personas = load_personas(agents_path)

    # Defer publisher + consumer to background task so /health responds immediately
    _consumer_task = asyncio.create_task(_start_worker(brokers, personas, compression))

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


@app.post("/reset")
async def reset() -> dict:
    """Clear claimed_tasks set so scenarios can be re-run cleanly."""
    count = len(_claimed_tasks)
    _claimed_tasks.clear()
    log.info("claimed_tasks_cleared", count_before=count)
    return {"status": "ok", "claimed_tasks_cleared": True}
