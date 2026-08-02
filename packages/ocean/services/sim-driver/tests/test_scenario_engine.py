"""Tests for refactored ScenarioEngine — Pydantic validation and PatientSimulator wiring."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

# Add service src to path
_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

# Ensure ocean-events is importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "libs" / "ocean-events" / "src"))

from src.models import ScenarioConfig
from src.scenario_engine import ScenarioEngine, load_scenario


class TestLoadScenario:
    """load_scenario returns a validated ScenarioConfig."""

    def test_returns_scenario_config(self) -> None:
        config = load_scenario("smoke_test")
        assert isinstance(config, ScenarioConfig)

    def test_smoke_test_has_fifty_patients(self) -> None:
        """smoke_test grew from 3 to 50 patients for broader happy-path coverage (phase 12)."""
        config = load_scenario("smoke_test")
        assert len(config.patients) == 50

    def test_smoke_test_patients_have_sources(self) -> None:
        config = load_scenario("smoke_test")
        assert {p.source for p in config.patients} == {"pocar", "impilo"}

    def test_invalid_scenario_raises(self, tmp_path: pathlib.Path) -> None:
        """A YAML file missing patient_id should raise ValidationError."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("name: bad\npatients:\n  - clinic_id: x\n    signals: []\n")
        with patch("src.scenario_engine._SCENARIOS_DIR", tmp_path), pytest.raises(ValidationError):
            load_scenario("bad")


_FIXTURE_SCENARIO = """\
name: fixture
compression_ratio: 720
patients:
  - patient_id: "sim-pt-fix-001"
    clinic_id: "clinic-demo"
    source: pocar
    signals:
      - {sim_hour: 0.1, type: glucose, value: 225, unit: "mg/dL", anomalous: true}
      - {sim_hour: 0.3, type: spo2, value: 85, unit: "%", anomalous: true}
  - patient_id: "sim-pt-fix-002"
    clinic_id: "clinic-demo"
    source: impilo
    signals:
      - {sim_hour: 0.2, type: weight, value: 76, unit: "kg", anomalous: false}
  - patient_id: "sim-pt-fix-003"
    clinic_id: "clinic-demo"
    source: pocar
    signals:
      - {sim_hour: 0.15, type: heart_rate, value: 130, unit: "bpm", anomalous: true}
"""


@pytest.fixture
def fixture_scenario_dir(tmp_path: pathlib.Path):
    """A scenario the tests control, so the property formulas are pinned against known
    inputs instead of whatever smoke_test.yaml currently holds (it grew 3 -> 50 patients
    once already and silently stranded the old hardcoded expectations)."""
    (tmp_path / "fixture.yaml").write_text(_FIXTURE_SCENARIO)
    with patch("src.scenario_engine._SCENARIOS_DIR", tmp_path):
        yield tmp_path


class TestScenarioEngineProperties:
    """ScenarioEngine exposes patient_count, expected_event_count, estimated_duration_seconds."""

    def test_patient_count(self, fixture_scenario_dir) -> None:
        pub = AsyncMock()
        engine = ScenarioEngine(scenario_name="fixture", publisher=pub)
        assert engine.patient_count == 3

    def test_expected_event_count(self, fixture_scenario_dir) -> None:
        """fixture: 4 signals total, 3 anomalous -> 4 + 3 = 7 events."""
        pub = AsyncMock()
        engine = ScenarioEngine(scenario_name="fixture", publisher=pub)
        assert engine.expected_event_count == 7

    def test_estimated_duration_seconds(self, fixture_scenario_dir) -> None:
        """Max sim_hour across all patients is 0.3 (patient 1).
        estimated = 0.3 * 3600 / 720 = 1.5 seconds."""
        pub = AsyncMock()
        engine = ScenarioEngine(scenario_name="fixture", publisher=pub)
        assert engine.estimated_duration_seconds == pytest.approx(1.5, rel=0.01)

    def test_scenario_name(self) -> None:
        pub = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)
        assert engine.scenario_name == "smoke_test"


class TestScenarioEngineRun:
    """ScenarioEngine.run creates PatientSimulator per patient and calls run()."""

    @pytest.mark.asyncio
    async def test_run_publishes_events(self) -> None:
        pub = AsyncMock()
        pub.publish = AsyncMock()
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=pub)

        with patch("src.scenario_engine.sim_sleep", new=AsyncMock(return_value=None)):
            with patch("src.clock.sim_sleep", new=AsyncMock(return_value=None)):
                await engine.run()

        # Expected: patient events + 2 bookend events (started + completed)
        # smoke_test has 50 patients; exact count depends on scenario config
        expected_patient_events = engine.expected_event_count
        assert pub.publish.call_count == expected_patient_events + 2

    @pytest.mark.asyncio
    async def test_run_does_not_import_state_machine(self) -> None:
        """Verify no imports of deleted modules."""
        import src.scenario_engine as mod

        source = pathlib.Path(mod.__file__).read_text()
        assert "state_machine" not in source
        assert "agent_runner" not in source
