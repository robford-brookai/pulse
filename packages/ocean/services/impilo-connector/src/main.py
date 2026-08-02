"""impilo-connector FastAPI app -- lifespan, health, and webhook router."""

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
from src.sqs_consumer import sqs_consumer_loop

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean")
    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_maker = session_maker

    # Addressing comes from the shared catalog, so there is no bus endpoint to configure here.
    publisher = EventBridgePublisher(db_session_maker=session_maker)
    app.state.publisher = publisher
    log.info("impilo_connector_started")

    heartbeat_task = asyncio.create_task(publish_heartbeat(publisher, "impilo-connector", "Impilo RPM"))

    sqs_queue_url = os.environ.get("SQS_QUEUE_URL")
    sqs_task = None
    if sqs_queue_url:
        sqs_task = asyncio.create_task(sqs_consumer_loop(publisher, sqs_queue_url))
        log.info("sqs_consumer_started", queue_url=sqs_queue_url)
    else:
        log.info("sqs_consumer_disabled")

    yield

    # Shutdown — cancel background tasks before closing publisher
    if sqs_task is not None:
        sqs_task.cancel()
        try:
            await sqs_task
        except asyncio.CancelledError:
            pass

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    # EventBridgePublisher holds no long-lived connection, so there is nothing to flush or close.
    await engine.dispose()
    log.info("impilo_connector_stopped")


app = FastAPI(title="impilo-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "impilo-connector", "version": "0.1.0"}
