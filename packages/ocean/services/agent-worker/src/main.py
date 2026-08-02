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
from src.publisher import build_publisher

__version__ = "0.1.0"

log = structlog.get_logger()

_consumer_task: asyncio.Task | None = None
_claimed_tasks: set[str] = set()


async def _start_worker(queue_url: str, personas, compression: float) -> None:
    """Initialize publisher and consumer in background.

    Runs after lifespan yields so /health is already responsive.
    """
    if not queue_url:
        log.error("consumer_not_started_missing_queue_url", env_var="SQS_QUEUE_URL")
        return
    # Off the loop: the boto3 client reads credential and config files as it is constructed.
    publisher = await asyncio.to_thread(build_publisher)
    log.info(
        "agent_worker_started",
        queue_url=queue_url,
        personas=[p.id for p in personas],
        compression_ratio=compression,
    )
    await run_consumer(personas, queue_url, publisher, _claimed_tasks)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task

    queue_url = os.environ.get("SQS_QUEUE_URL", "")
    agents_path = os.environ.get("AGENTS_MD_PATH", "/app/AGENTS.md")
    compression = float(os.environ.get("COMPRESSION_RATIO", "960"))

    personas = load_personas(agents_path)

    # Defer publisher + consumer to background task so /health responds immediately
    _consumer_task = asyncio.create_task(_start_worker(queue_url, personas, compression))

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
