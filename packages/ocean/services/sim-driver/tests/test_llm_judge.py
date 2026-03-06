"""Tests for LLM-as-judge scoring."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pathlib
import sys

import pytest

_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import src.llm_judge as _judge_mod
from src.llm_judge import judge_action


@pytest.mark.asyncio
async def test_judge_returns_required_fields():
    """judge_action returns dict with score, reasoning, needs_human."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"score": 0.85, "reasoning": "Appropriate action."}')]

    with patch.object(_judge_mod, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="glucose_anomaly",
            severity="URGENT",
            signals=[{"signal_type": "glucose", "value": 220, "unit": "mg/dL", "anomalous": True}],
            proposed_response="Approve outreach for high glucose.",
        )

    assert "score" in result
    assert "reasoning" in result
    assert "needs_human" in result
    assert isinstance(result["score"], float)
    assert isinstance(result["needs_human"], bool)


@pytest.mark.asyncio
async def test_judge_needs_human_when_score_low():
    """needs_human=True when score < 0.7."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"score": 0.5, "reasoning": "Uncertain decision."}')]

    with patch.object(_judge_mod, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await judge_action(
            agent_id="coordinator_bob",
            action="reject",
            alert_type="spo2_anomaly",
            severity="HIGH",
            signals=[],
            proposed_response="Reject outreach.",
        )

    assert result["needs_human"] is True


@pytest.mark.asyncio
async def test_judge_needs_human_for_critical_approve():
    """needs_human=True for approve on CRITICAL alert regardless of score."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"score": 0.95, "reasoning": "High confidence."}')]

    with patch.object(_judge_mod, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="spo2_anomaly",
            severity="CRITICAL",
            signals=[{"signal_type": "spo2", "value": 82, "unit": "%", "anomalous": True}],
            proposed_response="Approve outreach.",
        )

    assert result["needs_human"] is True


@pytest.mark.asyncio
async def test_judge_does_not_reraise_on_exception():
    """Judge handles API failure gracefully — returns default score 0.5."""
    with patch.object(_judge_mod, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API error"))
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="glucose_anomaly",
            severity="HIGH",
            signals=[],
            proposed_response="Approve.",
        )

    assert result["score"] == 0.5
    assert "needs_human" in result


@pytest.mark.asyncio
async def test_judge_handles_non_json_response():
    """Judge gracefully handles non-JSON response from Claude."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This looks correct to me.")]

    with patch.object(_judge_mod, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="glucose_anomaly",
            severity="URGENT",
            signals=[],
            proposed_response="Approve.",
        )

    # Should not raise, should return a valid result
    assert "score" in result
    assert "needs_human" in result
