"""Tests for PatientStateMachine FSM transitions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pathlib
import sys

import pytest

_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from src.state_machine import PatientStateMachine


def _make_sm() -> PatientStateMachine:
    return PatientStateMachine(
        patient_id="pt-test-001",
        clinic_id="clinic-test",
        assigned_agent="coordinator_alice",
        publisher=AsyncMock(),
        compression_ratio=720,
    )


def test_initial_state_is_idle():
    """FSM starts in 'idle' state."""
    sm = _make_sm()
    assert sm._state == "idle"


@pytest.mark.asyncio
async def test_non_anomalous_signal_stays_in_signal_published():
    """Non-anomalous signal doesn't trigger alert creation."""
    sm = _make_sm()
    sm._publisher.publish = AsyncMock()

    signal = {"type": "weight", "value": 75, "unit": "kg", "sim_hour": 1.0, "anomalous": False}
    await sm.process_signal(signal)

    assert sm._state == "signal_published"
    # Should have published exactly one signal event
    sm._publisher.publish.assert_awaited_once()
    call_topic = sm._publisher.publish.call_args.args[0]
    assert call_topic == "ocean.signals"


@pytest.mark.asyncio
async def test_anomalous_signal_triggers_full_loop():
    """Anomalous signal drives FSM from idle to dispatched/rejected."""
    sm = _make_sm()
    sm._publisher.publish = AsyncMock()

    with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        with patch("src.agent_runner.AsyncAnthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=MagicMock(content=[MagicMock(text="APPROVE — glucose elevated.")])
            )
            mock_anthropic.return_value = mock_client
            with patch("src.llm_judge.AsyncAnthropic") as mock_judge:
                mock_judge_client = MagicMock()
                mock_judge_client.messages.create = AsyncMock(
                    return_value=MagicMock(
                        content=[MagicMock(text='{"score": 0.9, "reasoning": "Correct decision."}')]
                    )
                )
                mock_judge.return_value = mock_judge_client
                with patch("src.human_gate.httpx.AsyncClient"):
                    signal = {
                        "type": "glucose",
                        "value": 250,
                        "unit": "mg/dL",
                        "sim_hour": 1.0,
                        "anomalous": True,
                    }
                    await sm.process_signal(signal)

    assert sm._state in ("dispatched", "rejected")
    # Should have published: signal, alert, task.created, task.claimed, ai.response.drafted, ai.output.*
    assert sm._publisher.publish.call_count >= 4


def test_infer_severity_glucose():
    """Glucose severity thresholds match plan spec."""
    sm = _make_sm()
    assert sm._infer_severity({"type": "glucose", "value": 350}) == "CRITICAL"
    assert sm._infer_severity({"type": "glucose", "value": 210}) == "URGENT"
    assert sm._infer_severity({"type": "glucose", "value": 180}) == "HIGH"


def test_infer_severity_spo2():
    """SpO2 severity thresholds match plan spec."""
    sm = _make_sm()
    assert sm._infer_severity({"type": "spo2", "value": 82}) == "CRITICAL"
    assert sm._infer_severity({"type": "spo2", "value": 88}) == "URGENT"
    assert sm._infer_severity({"type": "spo2", "value": 93}) == "HIGH"
