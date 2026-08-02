"""Tests for Pydantic scenario models: ScenarioConfig, PatientConfig, SignalConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.models import PatientConfig, ScenarioConfig, SignalConfig, resolve_source


class TestSignalConfig:
    """Validate individual signal configuration parsing."""

    def test_valid_signal(self) -> None:
        sig = SignalConfig(sim_hour=1.0, type="glucose", value=120)
        assert sig.sim_hour == 1.0
        assert sig.type == "glucose"
        assert sig.value == 120
        assert sig.unit == ""
        assert sig.anomalous is False
        assert sig.source is None
        assert sig.severity_hint is None

    def test_source_defaults_to_none(self) -> None:
        sig = SignalConfig(sim_hour=0.5, type="spo2", value=95)
        assert sig.source is None

    def test_severity_hint_accepts_valid_values(self) -> None:
        for hint in ("CRITICAL", "URGENT", "HIGH"):
            sig = SignalConfig(sim_hour=0.0, type="hr", value=80, severity_hint=hint)
            assert sig.severity_hint == hint

    def test_severity_hint_none_by_default(self) -> None:
        sig = SignalConfig(sim_hour=0.0, type="hr", value=80)
        assert sig.severity_hint is None

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            SignalConfig(sim_hour=0.0, type="hr", value=80, source="unknown")

    def test_valid_source_pocar(self) -> None:
        sig = SignalConfig(sim_hour=0.0, type="hr", value=80, source="pocar")
        assert sig.source == "pocar"

    def test_valid_source_impilo(self) -> None:
        sig = SignalConfig(sim_hour=0.0, type="hr", value=80, source="impilo")
        assert sig.source == "impilo"


class TestPatientConfig:
    """Validate patient configuration and default inheritance."""

    def test_valid_patient(self) -> None:
        p = PatientConfig(
            patient_id="p1",
            signals=[SignalConfig(sim_hour=0.0, type="glucose", value=100)],
        )
        assert p.patient_id == "p1"
        assert p.clinic_id == "clinic-demo"
        assert p.source == "pocar"
        assert len(p.signals) == 1

    def test_source_defaults_to_pocar(self) -> None:
        p = PatientConfig(
            patient_id="p2",
            signals=[],
        )
        assert p.source == "pocar"

    def test_missing_patient_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            PatientConfig(signals=[])

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            PatientConfig(patient_id="p3", source="unknown", signals=[])


class TestScenarioConfig:
    """Validate top-level scenario configuration."""

    def test_valid_scenario(self) -> None:
        sc = ScenarioConfig(
            name="test-scenario",
            patients=[
                PatientConfig(
                    patient_id="p1",
                    signals=[SignalConfig(sim_hour=0.0, type="glucose", value=100)],
                )
            ],
        )
        assert sc.name == "test-scenario"
        assert sc.description == ""
        assert sc.compression_ratio == 960
        assert len(sc.patients) == 1

    def test_compression_ratio_default(self) -> None:
        sc = ScenarioConfig(name="s", patients=[])
        assert sc.compression_ratio == 960

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioConfig(patients=[])


class TestResolveSource:
    """Validate source resolution: signal-level overrides patient-level."""

    def test_signal_source_overrides_patient(self) -> None:
        sig = SignalConfig(sim_hour=0.0, type="hr", value=80, source="impilo")
        pat = PatientConfig(patient_id="p1", source="pocar", signals=[sig])
        assert resolve_source(sig, pat) == "impilo"

    def test_falls_back_to_patient_source(self) -> None:
        sig = SignalConfig(sim_hour=0.0, type="hr", value=80)
        pat = PatientConfig(patient_id="p1", source="pocar", signals=[sig])
        assert resolve_source(sig, pat) == "pocar"

    def test_patient_impilo_fallback(self) -> None:
        sig = SignalConfig(sim_hour=0.0, type="hr", value=80)
        pat = PatientConfig(patient_id="p1", source="impilo", signals=[sig])
        assert resolve_source(sig, pat) == "impilo"
