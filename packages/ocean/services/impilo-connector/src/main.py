"""impilo-connector FastAPI app -- lifespan, health, and webhook router."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.producer import RedpandaPublisher
from src.receiver import router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean"
    )
    engine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_maker = session_maker

    bootstrap_servers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    publisher = RedpandaPublisher(
        bootstrap_servers=bootstrap_servers,
        db_session_maker=session_maker,
    )
    app.state.publisher = publisher
    log.info("impilo_connector_started", brokers=bootstrap_servers)

    yield

    # Shutdown
    await publisher.close()
    await engine.dispose()
    log.info("impilo_connector_stopped")


app = FastAPI(title="impilo-connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "impilo-connector", "version": "0.1.0"}
