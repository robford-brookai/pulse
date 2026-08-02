"""Unit tests for ResumeTokenStore — no Docker or real database needed.

Each test mocks AsyncSession so we verify SQL construction and parameter
passing without touching Postgres.
"""

from __future__ import annotations

import json
import pathlib

# The module under test lives outside the installed workspace packages,
# so we add its parent to sys.path.
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector" / "src"
sys.path.insert(0, str(_SRC))

from resume_token import ResumeTokenStore


@pytest.fixture
def store() -> ResumeTokenStore:
    return ResumeTokenStore()


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    # execute and commit are auto-created as AsyncMock children
    return session


SAMPLE_TOKEN = {"_data": "826478…", "clusterTime": {"$timestamp": {"t": 1, "i": 1}}}


# ---------- get_token ----------


async def test_get_token_returns_dict(store, mock_session):
    """get_token returns the stored dict when a row exists."""
    row = MagicMock()
    row.__getitem__ = lambda self, idx: SAMPLE_TOKEN  # row[0]
    result = MagicMock()
    result.fetchone.return_value = row
    mock_session.execute.return_value = result

    token = await store.get_token(mock_session, "alerts")

    assert token == SAMPLE_TOKEN
    mock_session.execute.assert_awaited_once()
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "SELECT resume_token" in sql_text
    assert "collection_name" in sql_text


async def test_get_token_not_found(store, mock_session):
    """get_token returns None when no row matches the collection."""
    result = MagicMock()
    result.fetchone.return_value = None
    mock_session.execute.return_value = result

    token = await store.get_token(mock_session, "nonexistent")

    assert token is None


async def test_get_token_parses_json_string(store, mock_session):
    """If the driver returns a raw JSON string, get_token parses it."""
    row = MagicMock()
    row.__getitem__ = lambda self, idx: json.dumps(SAMPLE_TOKEN)
    result = MagicMock()
    result.fetchone.return_value = row
    mock_session.execute.return_value = result

    token = await store.get_token(mock_session, "alerts")

    assert token == SAMPLE_TOKEN


# ---------- save_token ----------


async def test_save_token_upsert(store, mock_session):
    """save_token uses ON CONFLICT DO UPDATE (upsert) and commits."""
    await store.save_token(mock_session, "alerts", SAMPLE_TOKEN)

    mock_session.execute.assert_awaited_once()
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "INSERT INTO cdc_resume_tokens" in sql_text
    assert "ON CONFLICT" in sql_text
    assert "DO UPDATE" in sql_text

    # Verify token was JSON-serialized in the params
    params = mock_session.execute.call_args[0][1]
    assert json.loads(params["token"]) == SAMPLE_TOKEN

    mock_session.commit.assert_awaited_once()


async def test_save_token_upsert_updates_existing(store, mock_session):
    """The UPSERT SQL updates resume_token and updated_at on conflict."""
    await store.save_token(mock_session, "alerts", SAMPLE_TOKEN)

    sql_text = str(mock_session.execute.call_args[0][0])
    assert "ON CONFLICT (collection_name) DO UPDATE" in sql_text
    assert "EXCLUDED.resume_token" in sql_text


# ---------- delete_token ----------


async def test_delete_token(store, mock_session):
    """delete_token issues DELETE and commits."""
    await store.delete_token(mock_session, "alerts")

    mock_session.execute.assert_awaited_once()
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "DELETE FROM cdc_resume_tokens" in sql_text
    assert "collection_name" in sql_text
    mock_session.commit.assert_awaited_once()
