"""Pydantic v2 models for sim-driver scenario configuration.

Defines the three-layer config hierarchy: ScenarioConfig > PatientConfig > SignalConfig.
Loaded from YAML scenario files and validated at parse time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__version__ = "1.0.0"


class SignalConfig(BaseModel):
    """A single simulated signal reading within a patient timeline.

    Fields:
        sim_hour: When this signal fires in simulated time (hours from scenario start).
        type: Signal type identifier (e.g., "glucose", "spo2", "heart_rate").
        value: Numeric reading value.
        unit: Measurement unit (e.g., "mg/dL"). Empty string when unitless.
        anomalous: Whether this reading should trigger an alert event.
        source: Connector name override. When None, inherits from the parent
                PatientConfig.source via resolve_source().
        severity_hint: Explicit severity for anomalous signals. When set, bypasses
                       the value-based inference in PatientSimulator._infer_severity().
                       Only meaningful when anomalous=True.
    """

    sim_hour: float
    type: str
    value: float | int
    unit: str = ""
    anomalous: bool = False
    # None means "inherit from patient" -- resolved at runtime via resolve_source()
    source: Literal["pocar", "impilo"] | None = None
    # Optional override for severity inference; only CRITICAL/URGENT/HIGH are valid
    severity_hint: Literal["CRITICAL", "URGENT", "HIGH"] | None = None


class PatientConfig(BaseModel):
    """Configuration for one simulated patient within a scenario.

    The source field provides a default connector name for all signals belonging
    to this patient. Individual signals can override via SignalConfig.source.
    Default is "pocar" because it is the most common RPM connector in production.

    Fields:
        patient_id: Opaque patient identifier (no PHI).
        clinic_id: Clinic identifier for event payloads.
        source: Default source_system for this patient's signals.
        signals: Ordered list of signal readings to simulate.
    """

    patient_id: str
    clinic_id: str = "clinic-demo"
    # Default to "pocar" -- the primary RPM connector in production
    source: Literal["pocar", "impilo"] = "pocar"
    signals: list[SignalConfig]


class ScenarioConfig(BaseModel):
    """Top-level scenario definition loaded from YAML.

    Fields:
        name: Human-readable scenario identifier.
        description: Optional description of the scenario purpose.
        compression_ratio: How many simulated seconds map to one wall-clock second.
                          Default 960 means 1 sim-hour = 3.75 wall-seconds.
        patients: List of patient configurations to simulate concurrently.
    """

    name: str
    description: str = ""
    # 960x compression: 1 simulated hour = 3.75 wall-clock seconds
    compression_ratio: float = 960
    patients: list[PatientConfig]


def resolve_source(signal: SignalConfig, patient: PatientConfig) -> str:
    """Return the effective source_system for a signal.

    Override chain: signal-level source > patient-level default.
    If the signal has an explicit source, use it; otherwise fall back to
    the patient's default source.
    """
    # Signal-level override takes precedence over patient default
    return signal.source or patient.source
