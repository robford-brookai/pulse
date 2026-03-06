"""AI-01: AI summary generated using Claude with graph context.

Requirement: When a task.created event is processed, the system fetches graph
context (signals + alerts) for the patient via Hasura and generates a 1-2
sentence clinical summary using Claude (claude-sonnet-4-6).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import setup_service

setup_service("slack-bot")

import src.ai_summary as _ai_summary_mod  # noqa: E402
from src.ai_summary import generate_summary_with_context  # noqa: E402


@pytest.mark.asyncio
async def test_generate_summary_calls_anthropic_and_returns_text():
    """generate_summary_with_context returns (text, cited_signals) using Claude."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Patient has elevated glucose. Follow up needed.")]

    mock_messages = AsyncMock()
    mock_messages.create = AsyncMock(return_value=mock_response)

    graph_context = {
        "data": {
            "signals": [
                {"signal_type": "glucose", "value": 210.0, "unit": "mg/dL", "anomalous": True},
                {"signal_type": "weight", "value": 85.0, "unit": "kg", "anomalous": False},
            ],
            "alerts": [],
        }
    }

    with patch.object(_ai_summary_mod, "_client") as mock_client:
        mock_client.messages = mock_messages
        with patch.object(_ai_summary_mod, "fetch_patient_context", new=AsyncMock(return_value=graph_context)):
            summary, cited = await generate_summary_with_context(
                alert_type="glucose_high",
                severity="URGENT",
                patient_hash="abc123hash",
                timestamp="2026-03-06T07:00:00Z",
                hasura_url="http://hasura:8080",
                hasura_secret="test-secret",
            )

    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "glucose" in cited
    assert "weight" in cited


@pytest.mark.asyncio
async def test_generate_summary_includes_graph_signals_in_prompt():
    """Claude prompt includes signal data from graph context."""
    captured_prompts: list[str] = []

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Summary with signal context.")]

    async def capture_create(**kwargs):
        for msg in kwargs.get("messages", []):
            captured_prompts.append(msg.get("content", ""))
        return mock_response

    graph_context = {
        "data": {
            "signals": [
                {"signal_type": "spo2", "value": 88.0, "unit": "%", "anomalous": True},
            ],
            "alerts": [],
        }
    }

    with patch.object(_ai_summary_mod, "_client") as mock_client:
        mock_client.messages = AsyncMock()
        mock_client.messages.create = capture_create
        with patch.object(_ai_summary_mod, "fetch_patient_context", new=AsyncMock(return_value=graph_context)):
            await generate_summary_with_context(
                alert_type="spo2_low",
                severity="CRITICAL",
                patient_hash="def456hash",
                timestamp="2026-03-06T08:00:00Z",
                hasura_url="http://hasura:8080",
                hasura_secret="test-secret",
            )

    assert any("spo2" in p for p in captured_prompts), "Graph signal not in Claude prompt"


@pytest.mark.asyncio
async def test_generate_summary_degrades_gracefully_on_exception():
    """If Claude call fails, returns safe fallback — never re-raises."""
    with patch.object(_ai_summary_mod, "_client") as mock_client:
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        with patch.object(_ai_summary_mod, "fetch_patient_context", new=AsyncMock(return_value={})):
            summary, cited = await generate_summary_with_context(
                alert_type="any_alert",
                severity="HIGH",
                patient_hash="failhash",
                timestamp="2026-03-06T09:00:00Z",
                hasura_url="http://hasura:8080",
                hasura_secret="test-secret",
            )

    assert summary == "AI summary unavailable."
    assert cited == []
