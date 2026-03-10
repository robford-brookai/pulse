"""PatientSimulator drives one patient through their signal schedule.

Replaces the v1.0 PatientStateMachine (which drove the full care loop).
This class publishes ONLY signal.received and alert.created events --
downstream services (control-plane, graph-projection) handle the rest.

Events use the canonical BaseEvent envelope from ocean-events, making them
indistinguishable from events published by real connectors (pocar, impilo).
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure ocean-events is importable when running outside installed packages
try:
    _lib_path = Path(__file__).resolve().parents[3] / "libs" / "ocean-events" / "src"
    if _lib_path.exists():
        sys.path.insert(0, str(_lib_path))
except IndexError:
    pass  # In Docker, ocean-events is pip-installed

from ocean_events.base import BaseEvent  # noqa: E402

import structlog  # noqa: E402

from src.clock import sim_sleep  # noqa: E402
from src.models import PatientConfig, SignalConfig, resolve_source  # noqa: E402

log = structlog.get_logger()

__version__ = "1.0.0"


class PatientSimulator:
    """Drives one patient through their signal schedule, publishing source events.

    Replaces the v1.0 PatientStateMachine (which drove the full care loop).
    This class publishes ONLY signal.received and alert.created events --
    downstream services (control-plane, graph-projection) handle the rest.

    Events use the canonical BaseEvent envelope from ocean-events, making them
    indistinguishable from events published by real connectors (pocar, impilo).
    """

    def __init__(
        self,
        scenario_name: str,
        patient: PatientConfig,
        publisher: object,
        compression_ratio: float,
    ) -> None:
        self._scenario_name = scenario_name
        self._patient = patient
        self._publisher = publisher
        self._compression_ratio = compression_ratio

    @property
    def expected_event_count(self) -> int:
        """Total signals + one alert per anomalous signal."""
        anomalous = sum(1 for s in self._patient.signals if s.anomalous)
        return len(self._patient.signals) + anomalous

    async def run(self) -> None:
        """Iterate signals in sim_hour order. For each signal:

        1. sim_sleep for delay since last signal
        2. Build signal.received BaseEvent, serialize, publish to ocean.signals
        3. If anomalous, build alert.created BaseEvent, serialize, publish to ocean.alerts
        """
        prev_hour = 0.0
        for idx, signal in enumerate(self._patient.signals):
            delay = signal.sim_hour - prev_hour
            await sim_sleep(delay, self._compression_ratio)
            prev_hour = signal.sim_hour

            # Publish signal.received for every signal
            signal_event = self._build_signal_event(signal, idx)
            await self._publisher.publish(
                "ocean.signals", signal_event.model_dump(mode="json")
            )
            log.info(
                f"[SIM] Patient {self._patient.patient_id}: {signal.type} reading"
                f" {signal.value} {signal.unit}"
                f"{' (anomalous)' if signal.anomalous else ''}"
                f" at hour {signal.sim_hour}"
            )

            # Publish alert.created only for anomalous signals
            if signal.anomalous:
                alert_event = self._build_alert_event(signal, idx)
                await self._publisher.publish(
                    "ocean.alerts", alert_event.model_dump(mode="json")
                )
                severity = self._resolve_severity(signal)
                log.info(
                    f"[SIM] Patient {self._patient.patient_id}:"
                    f" ALERT {signal.type}_anomaly severity={severity}"
                )

    def _build_signal_event(self, signal: SignalConfig, idx: int) -> BaseEvent:
        """Construct a signal.received BaseEvent.

        Maps signal config fields to the BaseEvent envelope. The source_system
        is resolved from the signal/patient override chain, ensuring events
        look identical to those from real connectors.
        """
        event_id = self._deterministic_id(idx)
        source = resolve_source(signal, self._patient)
        return BaseEvent(
            event_id=event_id,
            event_type="signal.received",
            schema_version="1.0.0",
            timestamp=datetime.now(timezone.utc),
            source_system=source,
            entity_type="signal",
            entity_id=str(event_id),
            # "sim-" prefix enables filtering simulated events in observability
            correlation_id=f"sim-{event_id}",
            actor_id=None,
            payload={
                "signal_id": str(event_id),
                "patient_id": self._patient.patient_id,
                "clinic_id": self._patient.clinic_id,
                "signal_type": signal.type,
                "value": signal.value,
                "unit": signal.unit,
                "anomalous": signal.anomalous,
            },
        )

    def _build_alert_event(self, signal: SignalConfig, idx: int) -> BaseEvent:
        """Construct an alert.created BaseEvent for an anomalous signal.

        The alert event_id uses an "_alert" suffix in the hash input to
        prevent collision with the corresponding signal's event_id.
        """
        alert_id = self._deterministic_id(idx, suffix="_alert")
        source = resolve_source(signal, self._patient)
        severity = self._resolve_severity(signal)
        return BaseEvent(
            event_id=alert_id,
            event_type="alert.created",
            schema_version="1.0.0",
            timestamp=datetime.now(timezone.utc),
            source_system=source,
            entity_type="alert",
            entity_id=str(alert_id),
            # "sim-" prefix for traceability in logs and dashboards
            correlation_id=f"sim-{alert_id}",
            actor_id=None,
            payload={
                "alert_type": f"{signal.type}_anomaly",
                "severity": severity,
                "patient_id": self._patient.patient_id,
                "clinic_id": self._patient.clinic_id,
                "signal_type": signal.type,
                "signal_value": signal.value,
            },
        )

    def _deterministic_id(self, idx: int, suffix: str = "") -> uuid.UUID:
        """Generate a deterministic UUID from scenario, patient, and signal index.

        Deterministic IDs enable scenario replay idempotency -- running the
        same scenario twice produces identical event_ids, allowing dedup
        and replay verification in downstream consumers.
        """
        key = f"sim:{self._scenario_name}:{self._patient.patient_id}:{idx}{suffix}"
        return uuid.UUID(bytes=hashlib.sha256(key.encode()).digest()[:16])

    def _resolve_severity(self, signal: SignalConfig) -> str:
        """Return severity, preferring severity_hint over inference.

        If severity_hint is set on the signal config, use it directly.
        Otherwise fall back to value-based inference.
        """
        if signal.severity_hint is not None:
            return signal.severity_hint
        return self._infer_severity(signal.type, signal.value)

    @staticmethod
    def _infer_severity(signal_type: str, value: float | int) -> str:
        """Infer alert severity from signal type and value.

        Clinical thresholds (simplified for simulation):
        - glucose > 300 mg/dL: CRITICAL (immediate intervention needed)
        - spo2 < 90%: URGENT (hypoxemia risk)
        - All other anomalous readings: HIGH (requires attention)
        """
        # Dangerously high glucose requires immediate clinical response
        if signal_type == "glucose" and value > 300:
            return "CRITICAL"
        # SpO2 below 90% indicates significant hypoxemia
        if signal_type == "spo2" and value < 90:
            return "URGENT"
        # Default severity for other anomalous signals
        return "HIGH"
