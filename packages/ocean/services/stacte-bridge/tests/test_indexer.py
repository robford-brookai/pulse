"""Tests for indexer — sync_embeddings and semantic_search."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from src.indexer import semantic_search, sync_embeddings

# ---------------------------------------------------------------------------
# Mock helpers (same pattern as test_graph_search.py)
# ---------------------------------------------------------------------------


def _make_row(**kwargs):
    """Build a mock SQLAlchemy row with _mapping."""
    row = MagicMock()
    row._mapping = kwargs
    return row


def _make_result(*rows):
    """Build a mock execute() result."""
    result = MagicMock()
    result.fetchone = MagicMock(return_value=rows[0] if rows else None)
    result.fetchall = MagicMock(return_value=list(rows))
    return result


# ---------------------------------------------------------------------------
# sync_embeddings tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_embeddings_indexes_rows():
    """Happy path: 2 unindexed rows get embedded and updated."""
    row_a = _make_row(alert_id="a-1", alert_type="glucose_high", embedding=None)
    row_b = _make_row(alert_id="a-2", alert_type="spo2_low", embedding=None)

    select_result = _make_result(row_a, row_b)
    update_result = MagicMock()  # UPDATE returns don't matter

    call_count = [0]

    async def mock_execute(stmt, params=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return select_result
        return update_result

    session = AsyncMock()
    session.execute = mock_execute
    session.commit = AsyncMock()

    fake_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    with patch("src.indexer.embed_batch", new_callable=AsyncMock, return_value=fake_embeddings) as mock_embed:
        count = await sync_embeddings(session, entity_type="alerts", limit=100)

    assert count == 2
    mock_embed.assert_awaited_once_with(
        "alerts",
        [
            {"alert_id": "a-1", "alert_type": "glucose_high", "embedding": None},
            {"alert_id": "a-2", "alert_type": "spo2_low", "embedding": None},
        ],
    )
    # 1 SELECT + 2 UPDATEs = 3 execute calls
    assert call_count[0] == 3
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_embeddings_no_rows():
    """Empty result: no rows to embed, embed_batch not called."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_result())  # empty
    session.commit = AsyncMock()

    with patch("src.indexer.embed_batch", new_callable=AsyncMock) as mock_embed:
        count = await sync_embeddings(session, entity_type="tasks", limit=100)

    assert count == 0
    mock_embed.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_embeddings_unknown_entity_type():
    """Unknown entity_type raises ValueError."""
    session = AsyncMock()
    with pytest.raises(ValueError, match="Unknown entity_type: 'bogus'"):
        await sync_embeddings(session, entity_type="bogus")


# ---------------------------------------------------------------------------
# semantic_search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_search_returns_results():
    """Happy path: returns ranked results with distance field."""
    row_1 = _make_row(alert_id="a-1", alert_type="glucose_high", distance=0.12)
    row_2 = _make_row(alert_id="a-2", alert_type="spo2_low", distance=0.34)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_result(row_1, row_2))

    results = await semantic_search(
        session,
        query_embedding=[0.1, 0.2, 0.3],
        entity_type="alerts",
        top_k=5,
    )

    assert len(results) == 2
    assert results[0]["alert_id"] == "a-1"
    assert results[0]["distance"] == 0.12
    assert results[1]["alert_id"] == "a-2"
    assert results[1]["distance"] == 0.34


@pytest.mark.asyncio
async def test_semantic_search_unknown_entity_type():
    """Unknown entity_type raises ValueError."""
    session = AsyncMock()
    with pytest.raises(ValueError, match="Unknown entity_type: 'bogus'"):
        await semantic_search(session, query_embedding=[0.1], entity_type="bogus")
