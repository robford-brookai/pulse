"""Scenario engine -- loads YAML scenario definitions and runs patient simulations concurrently.

Validates YAML against Pydantic ScenarioConfig at load time. Each patient is driven
by a PatientSimulator that publishes signal.received and alert.created events.
"""
from __future__ import annotations

import asyncio
import pathlib

import structlog
import yaml

from src.clock import sim_sleep
from src.models import PatientConfig, ScenarioConfig
from src.patient_simulator import PatientSimulator

__version__ = "2.0.0"

log = structlog.get_logger()

_SCENARIOS_DIR = pathlib.Path(__file__).parent.parent / "scenarios"


def load_scenario(name: str) -> ScenarioConfig:
    """Load and validate a scenario from scenarios/{name}.yaml.

    Returns a validated ScenarioConfig. Raises pydantic.ValidationError
    if the YAML content does not conform to the schema.
    """
    path = _SCENARIOS_DIR / f"{name}.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    return ScenarioConfig.model_validate(raw)


class ScenarioEngine:
    """Runs all patients in a scenario concurrently using asyncio.gather.

    Uses Pydantic-validated ScenarioConfig and delegates per-patient work
    to PatientSimulator instances.
    """

    def __init__(self, scenario_name: str, publisher: object) -> None:
        self._config = load_scenario(scenario_name)
        self._publisher = publisher
        self._running = False

    @property
    def scenario_name(self) -> str:
        return self._config.name

    @property
    def compression_ratio(self) -> float:
        return self._config.compression_ratio

    @property
    def patient_count(self) -> int:
        return len(self._config.patients)

    @property
    def expected_event_count(self) -> int:
        """Sum of expected events across all patients."""
        return sum(
            PatientSimulator(
                self._config.name, p, self._publisher, self._config.compression_ratio
            ).expected_event_count
            for p in self._config.patients
        )

    @property
    def estimated_duration_seconds(self) -> float:
        """Wall-clock estimate: max sim_hour across all patients, compressed."""
        max_hour = 0.0
        for patient in self._config.patients:
            for signal in patient.signals:
                if signal.sim_hour > max_hour:
                    max_hour = signal.sim_hour
        return (max_hour * 3600) / self._config.compression_ratio

    async def run(self) -> None:
        """Schedule all patient signal streams and run them concurrently."""
        self._running = True
        log.info(
            "scenario_starting",
            name=self.scenario_name,
            patient_count=self.patient_count,
            compression_ratio=self._config.compression_ratio,
        )

        patient_tasks = [
            self._run_patient(p) for p in self._config.patients
        ]
        await asyncio.gather(*patient_tasks, return_exceptions=True)

        self._running = False
        log.info("scenario_completed", name=self.scenario_name)

    async def _run_patient(self, patient: PatientConfig) -> None:
        """Drive one patient through their scheduled signal sequence."""
        simulator = PatientSimulator(
            scenario_name=self._config.name,
            patient=patient,
            publisher=self._publisher,
            compression_ratio=self._config.compression_ratio,
        )
        await simulator.run()
