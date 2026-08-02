"""stacte-bridge FastAPI app — OCEAN graph search and STACTE integration."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
import structlog
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.crud_api import router as crud_router, get_session
from src.embedder import embed_texts, entity_to_text
from src.graph_search import get_entity_neighborhood
from src.indexer import semantic_search, sync_embeddings

log = structlog.get_logger()

_session_factory: async_sessionmaker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _session_factory
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://ocean:changeme@postgres:5432/ocean",
    )
    engine = create_async_engine(db_url, echo=False)
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    log.info("stacte_bridge_started", db_url=db_url.split("@")[-1])

    yield

    await engine.dispose()
    log.info("stacte_bridge_stopped")


app = FastAPI(title="stacte-bridge", version="0.1.0", lifespan=lifespan)


async def _get_session() -> AsyncSession:
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    async with _session_factory() as session:
        yield session


# Override the dependency in crud_router
app.dependency_overrides[get_session] = _get_session
app.include_router(crud_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "stacte-bridge"}


@app.post("/sync")
async def sync_entities(
    entity_type: str = Query(..., description="alerts|tasks|interactions|outcomes"),
    limit: int = Query(500, description="Max entities to embed per call"),
) -> dict:
    """Embed all unindexed entities of the given type.

    Intended to be called periodically by a cron job or webhook trigger.
    """
    valid_types = ("alerts", "tasks", "interactions", "outcomes")
    if entity_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"entity_type must be one of {valid_types}")

    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    async with _session_factory() as session:
        updated = await sync_embeddings(session, entity_type, limit=limit)

    return {"status": "ok", "entity_type": entity_type, "updated": updated}


@app.get("/search")
async def search_entities(
    q: str = Query(..., description="Natural language search query"),
    entity_type: str = Query("alerts", description="alerts|tasks|interactions|outcomes"),
    top_k: int = Query(10, description="Number of results"),
) -> dict:
    """Semantic search over embedded OCEAN entities."""
    valid_types = ("alerts", "tasks", "interactions", "outcomes")
    if entity_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"entity_type must be one of {valid_types}")

    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        query_embeddings = await embed_texts([q])
        if not query_embeddings:
            raise HTTPException(status_code=502, detail="Embedding service unavailable")
        query_vec = query_embeddings[0]
    except Exception as exc:
        log.error("search_embed_failed", query=q, error=str(exc))
        raise HTTPException(status_code=502, detail="Embedding failed") from exc

    async with _session_factory() as session:
        results = await semantic_search(session, query_vec, entity_type, top_k=top_k)

    return {"query": q, "entity_type": entity_type, "results": results}


@app.get("/graph/{entity_id}")
async def graph_neighborhood(
    entity_id: str,
    hops: int = Query(2, description="Number of hops to traverse"),
) -> dict[str, Any]:
    """Return the N-hop neighborhood for any entity ID."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    async with _session_factory() as session:
        return await get_entity_neighborhood(session, entity_id, hops=hops)
