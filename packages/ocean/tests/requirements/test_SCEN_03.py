"""SCEN-03: stress_test.yaml provides a 50-patient throughput scenario.

Requirement: The stress_test scenario has 50 patients producing 400+ expected
events, staggered across sim_hours to avoid thundering herd, with
compression_ratio 1920 for fast execution.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_SIM_DRIVER = Path(__file__).resolve().parents[2] / "services" / "sim-driver"
_SCENARIO_PATH = _SIM_DRIVER / "scenarios" / "stress_test.yaml"

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


def test_has_fifty_patients():
    scenario = _load_scenario()
    assert len(scenario.patients) == 50


def test_no_duplicate_patient_ids():
    scenario = _load_scenario()
    ids = [p.patient_id for p in scenario.patients]
    assert len(ids) == len(set(ids)), f"Duplicate patient_ids found: {len(ids) - len(set(ids))}"


def test_minimum_expected_events_above_400():
    """anomalous_count * 7 + non_anomalous_count * 1 >= 400."""
    scenario = _load_scenario()
    anomalous = 0
    non_anomalous = 0
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous:
                anomalous += 1
            else:
                non_anomalous += 1
    min_events = anomalous * 7 + non_anomalous * 1
    assert min_events >= 400, (
        f"Minimum expected events {min_events} < 400 "
        f"(anomalous={anomalous}, non_anomalous={non_anomalous})"
    )


def test_sim_hours_staggered():
    """At least 3 distinct sim_hour values across anomalous signals."""
    scenario = _load_scenario()
    sim_hours = set()
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous:
                sim_hours.add(signal.sim_hour)
    assert len(sim_hours) >= 3, (
        f"Only {len(sim_hours)} distinct sim_hours: {sorted(sim_hours)}"
    )


def test_compression_ratio_is_1920():
    scenario = _load_scenario()
    assert scenario.compression_ratio == 1920
