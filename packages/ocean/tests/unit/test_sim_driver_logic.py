"""sim-driver business logic: severity inference and LLM judge.

Sourced from test/cat6_business_logic.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import setup_service

setup_service("sim-driver")

import src.llm_judge as _judge_mod  # noqa: E402
from src.llm_judge import judge_action  # noqa: E402
from src.state_machine import PatientStateMachine  # noqa: E402


def _make_sm():
    return PatientStateMachine(
        patient_id="pt-test",
        clinic_id="clinic-test",
        assigned_agent="coordinator_alice",
        publisher=AsyncMock(),
        compression_ratio=720,
    )


@pytest.mark.parametrize("value,expected", [
    (350, "CRITICAL"), (210, "URGENT"), (180, "HIGH"),
])
def test_glucose_severity(value, expected):
    assert _make_sm()._infer_severity({"type": "glucose", "value": value}) == expected


@pytest.mark.parametrize("value,expected", [
    (82, "CRITICAL"), (88, "URGENT"), (93, "HIGH"),
])
def test_spo2_severity(value, expected):
    assert _make_sm()._infer_severity({"type": "spo2", "value": value}) == expected


def test_unknown_signal_type_defaults_to_high():
    assert _make_sm()._infer_severity({"type": "weight", "value": 100}) == "HIGH"


@pytest.mark.asyncio
async def test_judge_needs_human_when_score_below_threshold():
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text='{"score": 0.5, "reasoning": "Uncertain."}')]
    with patch.object(_judge_mod, "AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_result)
        mock_cls.return_value = mock_client
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="glucose_anomaly",
            severity="HIGH",
            signals=[],
            proposed_response="Call patient",
        )
    assert result["needs_human"] is True
    assert result["score"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_judge_needs_human_for_critical_approve():
    """CRITICAL alert + approve always requires human gate regardless of score."""
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text='{"score": 0.95, "reasoning": "High confidence."}')]
    with patch.object(_judge_mod, "AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_result)
        mock_cls.return_value = mock_client
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="glucose_anomaly",
            severity="CRITICAL",
            signals=[],
            proposed_response="Call patient",
        )
    assert result["needs_human"] is True


@pytest.mark.asyncio
async def test_judge_no_human_gate_for_high_score_non_critical():
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text='{"score": 0.85, "reasoning": "Appropriate."}')]
    with patch.object(_judge_mod, "AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_result)
        mock_cls.return_value = mock_client
        result = await judge_action(
            agent_id="coordinator_alice",
            action="approve",
            alert_type="glucose_anomaly",
            severity="HIGH",
            signals=[],
            proposed_response="Call patient",
        )
    assert result["needs_human"] is False
