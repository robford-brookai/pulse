"""Tests for scenario_engine — YAML loading and per-patient scheduling."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pathlib

import pytest
import sys

# Add service src to path
_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from src.scenario_engine import load_scenario, ScenarioEngine


def test_load_smoke_test_scenario():
    """smoke_test.yaml loads with expected structure."""
    scenario = load_scenario("smoke_test")
    assert scenario["name"] == "smoke_test"
    assert "compression_ratio" in scenario
    patients = scenario["patients"]
    assert len(patients) >= 3
    # Each patient has at least one signal
    for p in patients:
        assert "patient_id" in p
        assert "signals" in p
        assert len(p["signals"]) >= 1


def test_load_one_day_scenario():
    """one_day.yaml loads with 5 patients."""
    scenario = load_scenario("one_day")
    assert scenario["name"] == "one_day"
    assert scenario["compression_ratio"] == 960
    assert len(scenario["patients"]) >= 5


def test_scenario_engine_name():
    """ScenarioEngine exposes scenario name."""
    pub = AsyncMock()
    engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)
    assert engine.scenario_name == "smoke_test"
    assert engine.compression_ratio > 0


@pytest.mark.asyncio
async def test_scenario_engine_run_calls_publisher():
    """ScenarioEngine.run publishes at least one event per anomalous signal."""
    pub = AsyncMock()
    pub.publish = AsyncMock()

    engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

    # Patch sim_sleep and claim delay to return immediately
    with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        with patch("src.agent_runner.AsyncAnthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=MagicMock(content=[MagicMock(text="APPROVE — glucose is high.")])
            )
            mock_anthropic.return_value = mock_client
            with patch("src.llm_judge.AsyncAnthropic") as mock_judge:
                mock_judge_client = MagicMock()
                mock_judge_client.messages.create = AsyncMock(
                    return_value=MagicMock(
                        content=[MagicMock(text='{"score": 0.85, "reasoning": "Appropriate action."}')]
                    )
                )
                mock_judge.return_value = mock_judge_client
                with patch("src.human_gate.httpx.AsyncClient"):
                    await engine.run()

    # At minimum: signal events + alert events were published
    assert pub.publish.call_count > 0
