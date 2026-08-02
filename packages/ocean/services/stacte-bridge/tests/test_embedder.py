"""Tests for VoyageAI embedder — entity text conversion and batch embedding."""
from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import src.embedder as _embedder_mod
from src.embedder import entity_to_text, embed_batch, EMBED_DIMS


def test_alert_entity_to_text():
    """Alert row produces text with severity, type, patient prefix, status."""
    row = {
        "alert_id": "alert-001",
        "patient_id": "patient-12345678",
        "alert_type": "glucose_high",
        "severity": "URGENT",
        "status": "open",
        "created_at": "2026-03-06T09:00:00Z",
    }
    text = entity_to_text("alerts", row)
    assert "URGENT" in text
    assert "glucose_high" in text
    assert "patient=" in text  # patient prefix included


def test_task_entity_to_text():
    """Task row produces text with type, priority, status, alert prefix."""
    row = {
        "task_id": "task-001",
        "task_type": "outreach",
        "priority": "high",
        "status": "claimed",
        "alert_id": "alert-abcdefgh",
    }
    text = entity_to_text("tasks", row)
    assert "outreach" in text
    assert "high" in text
    assert "claimed" in text
    assert "alert-ab" in text


def test_interaction_entity_to_text():
    """Interaction row produces text with interaction_type, outcome, patient prefix."""
    row = {
        "interaction_id": "int-001",
        "interaction_type": "call",
        "outcome": "completed",
        "patient_id": "patient-xyz",
    }
    text = entity_to_text("interactions", row)
    assert "call" in text
    assert "completed" in text


def test_outcome_entity_to_text():
    """Outcome row produces text with outcome_type and resolution_status."""
    row = {
        "outcome_id": "out-001",
        "outcome_type": "call_completed",
        "resolution_status": "resolved",
        "notes": None,
    }
    text = entity_to_text("outcomes", row)
    assert "call_completed" in text
    assert "resolved" in text


@pytest.mark.asyncio
async def test_embed_batch_calls_voyage():
    """embed_batch calls VoyageAI and returns embeddings for each row."""
    rows = [
        {"alert_id": "a1", "patient_id": "p1", "alert_type": "g_high", "severity": "URGENT",
         "status": "open", "created_at": "2026-01-01"},
        {"alert_id": "a2", "patient_id": "p2", "alert_type": "spo2_low", "severity": "CRITICAL",
         "status": "open", "created_at": "2026-01-01"},
    ]

    fake_embeddings = [[0.1] * EMBED_DIMS, [0.2] * EMBED_DIMS]
    mock_result = MagicMock()
    mock_result.embeddings = fake_embeddings

    with patch.object(_embedder_mod, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=mock_result)
        mock_get_client.return_value = mock_client

        result = await embed_batch("alerts", rows)

    assert len(result) == 2
    assert all(len(v) == EMBED_DIMS for v in result)
    mock_client.embed.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_batch_empty_returns_empty():
    """embed_batch with empty rows returns empty list without calling API."""
    with patch.object(_embedder_mod, "_get_client") as mock_get_client:
        result = await embed_batch("alerts", [])

    assert result == []
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
async def test_embed_batch_handles_api_failure():
    """embed_batch returns zero vectors on API failure instead of raising."""
    rows = [{"alert_id": "a1", "patient_id": "p1", "alert_type": "t", "severity": "HIGH",
             "status": "open", "created_at": "2026-01-01"}]

    with patch.object(_embedder_mod, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(side_effect=RuntimeError("API failure"))
        mock_get_client.return_value = mock_client

        result = await embed_batch("alerts", rows)

    # Should return zero vector instead of raising
    assert len(result) == 1
    assert result[0] == [0.0] * EMBED_DIMS
