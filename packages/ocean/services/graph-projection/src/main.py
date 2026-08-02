"""graph-projection FastAPI app — health endpoint and consumer background task."""

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

    bootstrap_servers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    log.info("starting_graph_consumer", brokers=bootstrap_servers)
    asyncio.create_task(consumer.run_consumer(session_maker, bootstrap_servers))

    yield

    await engine.dispose()
    log.info("graph_projection_stopped")


app = FastAPI(title="graph-projection", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "graph-projection", "version": "0.1.0"}
