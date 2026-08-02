# AUDIT-04 GATE: Anthropic HIPAA BAA must be confirmed before deploying to production.
# This service is safe to build and test locally. Production deploy is blocked until BAA is in place.
# Track BAA status: [link to Linear/Notion issue]
"""control-plane FastAPI app — health endpoint and consumer background task."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src import consumer

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean")
    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from src.producer import ControlPlanePublisher

    # The session maker is what gives this site the `failed_webhooks` fallback it lacked under
    # Kafka: without it a bus rejection would only be logged.
    publisher = ControlPlanePublisher(db_session_maker=session_maker)
    log.info("control_plane_publisher_created")

    queue_url = os.environ.get("SQS_QUEUE_URL")
    if queue_url:
        log.info("starting_control_plane_consumer", queue_url=queue_url)
        asyncio.create_task(consumer.run_consumer(session_maker, queue_url, publisher=publisher))
    else:
        # No queue, no consumer: the service still serves /health and the
        # escalation poller, and the gap is loud in logs.
        log.warning("consumer_disabled_no_queue_url", env_var="SQS_QUEUE_URL")

    # Escalation: rehydrate missed items, then start background poller
    from src.escalation import rehydrate_and_catch_up, run_escalation_poller

    async with session_maker() as session, session.begin():
        caught_up = await rehydrate_and_catch_up(session, publisher)
        if caught_up:
            log.info("escalation_catch_up_complete", escalated=caught_up)
    asyncio.create_task(run_escalation_poller(session_maker, publisher))

    yield

    await engine.dispose()
    log.info("control_plane_stopped")


app = FastAPI(title="control-plane", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "control-plane", "version": "0.1.0"}
