"""VoyageAI voyage-3 embeddings for OCEAN graph entities.

Converts entity rows into searchable text and embeds them using voyage-3
(1024-dimensional vectors). Processes in batches of 128 for efficiency.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

_VOYAGE_MODEL = "voyage-3"
EMBED_DIMS = 1024
BATCH_SIZE = 128

_client = None


def _get_client():
    """Return the VoyageAI async client (lazy import to avoid hard dep at test time)."""
    global _client
    if _client is None:
        import voyageai  # noqa: PLC0415
        api_key = os.environ.get("VOYAGE_API_KEY", "")
        _client = voyageai.AsyncClient(api_key=api_key)
    return _client


def entity_to_text(entity_type: str, row: dict[str, Any]) -> str:
    """Convert an entity row to an embeddable text string.

    Uses only categorical and numeric fields — no free-text clinical notes.
    """
    if entity_type == "alerts":
        return (
            f"[{row.get('severity', '')}] {row.get('alert_type', '')} "
            f"patient={str(row.get('patient_id', ''))[:8]} "
            f"status={row.get('status', '')} "
            f"at {row.get('created_at', '')}"
        )
    elif entity_type == "tasks":
        return (
            f"Task {row.get('task_type', '')} "
            f"priority={row.get('priority', '')} "
            f"status={row.get('status', '')} "
            f"alert={str(row.get('alert_id', ''))[:8]}"
        )
    elif entity_type == "interactions":
        return (
            f"Call {row.get('interaction_type', '')} "
            f"outcome={row.get('outcome', '')} "
            f"patient={str(row.get('patient_id', ''))[:8]}"
        )
    elif entity_type == "outcomes":
        return (
            f"Outcome {row.get('outcome_type', '')} "
            f"resolution={row.get('resolution_status', '')} "
            f"notes={row.get('notes', '') or ''}"
        )
    return str(row)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts using voyage-3. Returns list of 1024-dim vectors."""
    if not texts:
        return []
    client = _get_client()
    result = await client.embed(texts, model=_VOYAGE_MODEL)
    return result.embeddings


async def embed_batch(
    entity_type: str,
    rows: list[dict[str, Any]],
) -> list[list[float]]:
    """Convert rows to text and embed in batches of BATCH_SIZE."""
    texts = [entity_to_text(entity_type, r) for r in rows]
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        try:
            embeddings = await embed_texts(batch)
            all_embeddings.extend(embeddings)
        except Exception:
            log.error("embed_batch_failed", entity_type=entity_type, batch_start=i)
            # Return zero vectors for failed batch to maintain positional alignment
            all_embeddings.extend([[0.0] * EMBED_DIMS] * len(batch))

    return all_embeddings
