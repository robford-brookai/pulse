"""SCEN-01: smoke_test.yaml provides a 3-patient happy-path scenario.

Requirement: The smoke_test scenario has 3 patients, all anomalous signals
carry severity_hint for deterministic approve path, and compression_ratio
keeps the scenario under 2 minutes wall-clock time.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_SIM_DRIVER = Path(__file__).resolve().parents[2] / "services" / "sim-driver"
_SCENARIO_PATH = _SIM_DRIVER / "scenarios" / "smoke_test.yaml"

# Import models from sim-driver without polluting sys.path
_spec = importlib.util.spec_from_file_location(
    "sim_driver_models", _SIM_DRIVER / "src" / "models.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Rebuild all models with the module's full namespace to resolve forward refs
_ns = {k: v for k, v in vars(_mod).items() if not k.startswith("_")}
_mod.SignalConfig.model_rebuild(_types_namespace=_ns)
_mod.PatientConfig.model_rebuild(_types_namespace=_ns)
_mod.ScenarioConfig.model_rebuild(_types_namespace=_ns)
ScenarioConfig = _mod.ScenarioConfig


def _load_scenario():
    raw = yaml.safe_load(_SCENARIO_PATH.read_text())
    return ScenarioConfig(**raw)


def test_has_three_patients():
    scenario = _load_scenario()
    assert len(scenario.patients) == 3


def test_all_anomalous_signals_have_severity_hint():
    scenario = _load_scenario()
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous:
                assert signal.severity_hint is not None, (
                    f"Patient {patient.patient_id} signal {signal.type} missing severity_hint"
                )


def test_anomalous_signals_are_critical():
    """Happy-path requires CRITICAL for highest approve probability."""
    scenario = _load_scenario()
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous:
                assert signal.severity_hint == "CRITICAL", (
                    f"Patient {patient.patient_id} signal {signal.type} has "
                    f"severity_hint={signal.severity_hint}, expected CRITICAL"
                )


def test_compression_ratio_under_two_minutes():
    """With compression_ratio 720, max sim_hour 0.3 -> 0.3*3600/720 = 1.5s."""
    scenario = _load_scenario()
    max_sim_hour = max(
        signal.sim_hour
        for patient in scenario.patients
        for signal in patient.signals
    )
    wall_seconds = max_sim_hour * 3600 / scenario.compression_ratio
    assert wall_seconds < 120, f"Scenario would take {wall_seconds:.1f}s, exceeds 2 min"


def test_compression_ratio_is_720():
    scenario = _load_scenario()
    assert scenario.compression_ratio == 720
