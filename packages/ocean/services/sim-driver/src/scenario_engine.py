"""Scenario engine -- loads YAML scenario definitions and runs patient simulations concurrently.

Validates YAML against Pydantic ScenarioConfig at load time. Each patient is driven
by a PatientSimulator that publishes signal.received and alert.created events.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import time
import uuid
from datetime import UTC, datetime

import structlog
import yaml
from ocean_events.base import BaseEvent

from src.clock import sim_sleep  # noqa: F401  — patch target for tests
from src.models import PatientConfig, ScenarioConfig
from src.patient_simulator import PatientSimulator
from src.publisher import DOMAIN_OPS

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
            PatientSimulator(self._config.name, p, self._publisher, self._config.compression_ratio).expected_event_count
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
        """Schedule all patient signal streams and run them concurrently.

        Publishes scenario.started before patients run and
        scenario.completed with stats after all patients finish.
        """
        self._running = True
        start_time = time.monotonic()
        patient_ids = [p.patient_id for p in self._config.patients]

        log.info(
            "scenario_starting",
            name=self.scenario_name,
            patient_count=self.patient_count,
            compression_ratio=self._config.compression_ratio,
        )

        # Publish scenario.started bookend
        await self._publish_bookend(
            event_type="scenario.started",
            payload={
                "scenario_name": self.scenario_name,
                "patients": patient_ids,
                "flow_combos": self.patient_count,
            },
        )

        patient_tasks = [self._run_patient(p) for p in self._config.patients]
        await asyncio.gather(*patient_tasks, return_exceptions=True)

        elapsed = time.monotonic() - start_time
        self._running = False

        # Count events from publisher calls for stats
        alerts = sum(1 for p in self._config.patients for s in p.signals if s.anomalous)

        # Publish scenario.completed bookend
        await self._publish_bookend(
            event_type="scenario.completed",
            payload={
                "scenario_name": self.scenario_name,
                "patients_count": len(patient_ids),
                "alerts_generated": alerts,
                "tasks_created": alerts,
                "duration_seconds": round(elapsed, 2),
            },
        )

        log.info("scenario_completed", name=self.scenario_name)

    async def _publish_bookend(
        self,
        event_type: str,
        payload: dict,
    ) -> None:
        """Publish a scenario bookend event to the "ops" domain."""
        key = f"sim:{self.scenario_name}:{event_type}"
        event_id = uuid.UUID(bytes=hashlib.sha256(key.encode()).digest()[:16])
        event = BaseEvent(
            event_id=event_id,
            event_type=event_type,
            schema_version="1.0.0",
            timestamp=datetime.now(UTC),
            source_system="sim-driver",
            entity_type="signal",
            entity_id=self.scenario_name,
            correlation_id=f"sim-{event_id}",
            actor_id=None,
            payload=payload,
        )
        await self._publisher.publish(DOMAIN_OPS, event.model_dump(mode="json"))

    async def _run_patient(self, patient: PatientConfig) -> None:
        """Drive one patient through their scheduled signal sequence."""
        simulator = PatientSimulator(
            scenario_name=self._config.name,
            patient=patient,
            publisher=self._publisher,
            compression_ratio=self._config.compression_ratio,
        )
        await simulator.run()
