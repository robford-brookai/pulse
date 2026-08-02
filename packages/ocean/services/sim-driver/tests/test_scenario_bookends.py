"""Tests for sim-driver scenario.started and scenario.completed bookend events.

Plan 15-02 Task 2: Verifies ScenarioEngine publishes scenario.started at run
start and scenario.completed at run end to the "ops" domain, using BaseEvent
envelope with source_system="sim-driver".
"""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock, patch

import pytest

# Add service src to path
_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

# Ensure ocean-events is importable
sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[3] / "libs" / "ocean-events" / "src"),
)


class TestScenarioBookendEvents:
    """ScenarioEngine publishes bookend events to the "ops" domain."""

    @pytest.mark.asyncio
    async def test_publishes_scenario_started_at_run_start(self):
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        # Find the scenario.started event among all publish calls
        started_calls = [
            c
            for c in pub.publish.call_args_list
            if c[0][0] == "ops" and c[0][1].get("event_type") == "scenario.started"
        ]
        assert len(started_calls) == 1, "Expected exactly one scenario.started event on the 'ops' domain"

    @pytest.mark.asyncio
    async def test_publishes_scenario_completed_at_run_end(self):
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        completed_calls = [
            c
            for c in pub.publish.call_args_list
            if c[0][0] == "ops" and c[0][1].get("event_type") == "scenario.completed"
        ]
        assert len(completed_calls) == 1, "Expected exactly one scenario.completed event on the 'ops' domain"

    @pytest.mark.asyncio
    async def test_scenario_started_has_required_fields(self):
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        started_event = next(
            c[0][1]
            for c in pub.publish.call_args_list
            if c[0][0] == "ops" and c[0][1].get("event_type") == "scenario.started"
        )
        assert started_event["source_system"] == "sim-driver"
        payload = started_event["payload"]
        assert payload["scenario_name"] == "smoke_test"
        assert "patients" in payload
        assert isinstance(payload["patients"], list)

    @pytest.mark.asyncio
    async def test_scenario_completed_has_stats(self):
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        completed_event = next(
            c[0][1]
            for c in pub.publish.call_args_list
            if c[0][0] == "ops" and c[0][1].get("event_type") == "scenario.completed"
        )
        assert completed_event["source_system"] == "sim-driver"
        payload = completed_event["payload"]
        assert payload["scenario_name"] == "smoke_test"
        assert "patients_count" in payload
        assert "duration_seconds" in payload

    @pytest.mark.asyncio
    async def test_scenario_started_published_before_patient_events(self):
        """scenario.started should be the first published event."""
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        first_call = pub.publish.call_args_list[0]
        assert first_call[0][0] == "ops"
        assert first_call[0][1].get("event_type") == "scenario.started"

    @pytest.mark.asyncio
    async def test_scenario_completed_published_after_patient_events(self):
        """scenario.completed should be the last published event."""
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        last_call = pub.publish.call_args_list[-1]
        assert last_call[0][0] == "ops"
        assert last_call[0][1].get("event_type") == "scenario.completed"

    @pytest.mark.asyncio
    async def test_uses_base_event_envelope(self):
        """Events should have BaseEvent envelope fields."""
        from src.scenario_engine import ScenarioEngine

        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with (
            patch(
                "src.scenario_engine.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.clock.sim_sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            await engine.run()

        started_event = next(
            c[0][1]
            for c in pub.publish.call_args_list
            if c[0][0] == "ops" and c[0][1].get("event_type") == "scenario.started"
        )
        # BaseEvent envelope fields
        assert "event_id" in started_event
        assert "timestamp" in started_event
        assert "entity_type" in started_event
        assert "correlation_id" in started_event
