"""pgvector indexer — embeds unindexed entities and upserts vector columns.

Processes entities WHERE embedding IS NULL in batches, then UPDATEs the
vector column. Uses voyage-3 via embedder.py.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
import structlog

from src.embedder import embed_batch

log = structlog.get_logger()

# Mapping: entity_type → (table name, primary key column)
_ENTITY_TABLE_MAP = {
    "alerts": ("alerts", "alert_id"),
    "tasks": ("tasks", "task_id"),
    "interactions": ("interactions", "interaction_id"),
    "outcomes": ("outcomes", "outcome_id"),
}


async def sync_embeddings(
    session,
    entity_type: str,
    limit: int = 500,
) -> int:
    """Embed all unindexed rows for entity_type and upsert vector column.

    Returns the number of entities embedded.
    """
    config = _ENTITY_TABLE_MAP.get(entity_type)
    if config is None:
        raise ValueError(f"Unknown entity_type: {entity_type!r}")

    table, pk_col = config

    # Fetch unindexed rows
    result = await session.execute(
        sa.text(f"SELECT * FROM {table} WHERE embedding IS NULL LIMIT :limit"),
        {"limit": limit},
    )
    rows = [dict(r._mapping) for r in result.fetchall()]

    if not rows:
        log.info("no_unindexed_rows", entity_type=entity_type)
        return 0

    log.info("indexing_entities", entity_type=entity_type, count=len(rows))
    embeddings = await embed_batch(entity_type, rows)

    # Upsert embeddings back to the table
    updated = 0
    for row, embedding in zip(rows, embeddings):
        entity_id = row[pk_col]
        # pgvector expects list → str cast via ::vector
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        await session.execute(
            sa.text(f"UPDATE {table} SET embedding = :vec::vector WHERE {pk_col} = :entity_id"),
            {"vec": vec_str, "entity_id": entity_id},
        )
        updated += 1

    await session.commit()
    log.info("embeddings_indexed", entity_type=entity_type, updated=updated)
    return updated


async def semantic_search(
    session,
    query_embedding: list[float],
    entity_type: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Find the top_k most similar entities by cosine similarity.

    Uses pgvector's <=> operator (cosine distance, lower = more similar).
    """
    config = _ENTITY_TABLE_MAP.get(entity_type)
    if config is None:
        raise ValueError(f"Unknown entity_type: {entity_type!r}")

    table, pk_col = config
    vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    result = await session.execute(
        sa.text(
            f"SELECT *, (embedding <=> :vec::vector) AS distance "
            f"FROM {table} "
            f"WHERE embedding IS NOT NULL "
            f"ORDER BY embedding <=> :vec::vector "
            f"LIMIT :top_k"
        ),
        {"vec": vec_str, "top_k": top_k},
    )
    return [dict(r._mapping) for r in result.fetchall()]
