"""Scenario engine — loads YAML scenario definitions and runs patient simulations concurrently."""
from __future__ import annotations

import asyncio
import pathlib

import structlog
import yaml

log = structlog.get_logger()

_SCENARIOS_DIR = pathlib.Path(__file__).parent.parent / "scenarios"


def load_scenario(name: str) -> dict:
    """Load and parse a scenario from scenarios/{name}.yaml."""
    path = _SCENARIOS_DIR / f"{name}.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


class ScenarioEngine:
    """Runs all patients in a scenario concurrently using asyncio.gather."""

    def __init__(self, scenario_name: str, publisher) -> None:
        self._scenario = load_scenario(scenario_name)
        self._publisher = publisher
        self._compression_ratio = float(self._scenario.get("compression_ratio", 960))
        self._running = False

    @property
    def scenario_name(self) -> str:
        return self._scenario.get("name", "unknown")

    @property
    def compression_ratio(self) -> float:
        return self._compression_ratio

    async def run(self) -> None:
        """Schedule all patient signal streams and run them concurrently."""
        from src.state_machine import PatientStateMachine
        from src.clock import sim_sleep

        self._running = True
        patients = self._scenario.get("patients", [])
        log.info(
            "scenario_starting",
            name=self.scenario_name,
            patient_count=len(patients),
            compression_ratio=self._compression_ratio,
        )

        patient_tasks = [
            self._run_patient(p) for p in patients
        ]
        await asyncio.gather(*patient_tasks, return_exceptions=True)

        self._running = False
        log.info("scenario_completed", name=self.scenario_name)

    async def _run_patient(self, patient_config: dict) -> None:
        """Drive one patient through their scheduled signal sequence."""
        from src.state_machine import PatientStateMachine
        from src.clock import sim_sleep

        patient_id = patient_config["patient_id"]
        sm = PatientStateMachine(
            patient_id=patient_id,
            clinic_id=patient_config.get("clinic_id", "clinic-demo"),
            assigned_agent=patient_config.get("assigned_agent", "coordinator_alice"),
            publisher=self._publisher,
            compression_ratio=self._compression_ratio,
        )

        signals = sorted(patient_config.get("signals", []), key=lambda s: s["sim_hour"])
        prev_hour = 0.0

        for signal in signals:
            delay_hours = signal["sim_hour"] - prev_hour
            if delay_hours > 0:
                await sim_sleep(delay_hours, self._compression_ratio)
            prev_hour = signal["sim_hour"]

            try:
                await sm.process_signal(signal)
            except Exception:
                log.exception("patient_signal_error", patient_id=patient_id)
