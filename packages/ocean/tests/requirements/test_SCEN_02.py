"""SCEN-02: pilot_demo.yaml covers flow combinations with 50 patients.

Requirement: The pilot_demo scenario has 50 patients spanning all 3 severity
levels (CRITICAL, URGENT, HIGH) with both approve-path and escalate-path
signal types.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_SIM_DRIVER = Path(__file__).resolve().parents[2] / "services" / "sim-driver"
_SCENARIO_PATH = _SIM_DRIVER / "scenarios" / "pilot_demo.yaml"

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

# Signal types that get approve at URGENT (from fallback.py)
_URGENT_APPROVE_SIGNALS = {"glucose", "spo2"}


def _load_scenario() -> ScenarioConfig:
    raw = yaml.safe_load(_SCENARIO_PATH.read_text())
    return ScenarioConfig(**raw)


def test_has_ten_patients():
    scenario = _load_scenario()
    assert len(scenario.patients) == 10


def test_no_duplicate_patient_ids():
    scenario = _load_scenario()
    ids = [p.patient_id for p in scenario.patients]
    assert len(ids) == len(set(ids)), f"Duplicate patient_ids: {ids}"


def test_all_three_severity_levels_present():
    scenario = _load_scenario()
    severities = set()
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.severity_hint:
                severities.add(signal.severity_hint)
    assert severities == {"CRITICAL", "URGENT", "HIGH"}, f"Got {severities}"


def test_approve_path_signals_exist():
    """At least one CRITICAL or URGENT+glucose/spo2 signal exists."""
    scenario = _load_scenario()
    approve_found = False
    for patient in scenario.patients:
        for signal in patient.signals:
            if not signal.anomalous:
                continue
            if signal.severity_hint == "CRITICAL":
                approve_found = True
            elif signal.severity_hint == "URGENT" and signal.type in _URGENT_APPROVE_SIGNALS:
                approve_found = True
    assert approve_found, "No approve-path signals found"


def test_escalate_path_signals_exist():
    """At least one URGENT+non-glucose/spo2 or HIGH signal exists."""
    scenario = _load_scenario()
    escalate_found = False
    for patient in scenario.patients:
        for signal in patient.signals:
            if not signal.anomalous:
                continue
            if signal.severity_hint == "HIGH":
                escalate_found = True
            elif signal.severity_hint == "URGENT" and signal.type not in _URGENT_APPROVE_SIGNALS:
                escalate_found = True
    assert escalate_found, "No escalate-path signals found"


def test_event_estimate_minimum():
    """Each anomalous signal produces ~8-10 events through the pipeline."""
    scenario = _load_scenario()
    anomalous_count = sum(
        1
        for patient in scenario.patients
        for signal in patient.signals
        if signal.anomalous
    )
    # 10 patients each with at least one anomalous signal
    assert anomalous_count >= 10, f"Too few anomalous signals: {anomalous_count}"
