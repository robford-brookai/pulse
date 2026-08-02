"""SCEN-04: edge_cases.yaml covers false positives, concurrent claims, retries, escalation.

Requirement: The edge_cases scenario includes non-anomalous signals for false
positive testing, concurrent sim_hours for claim competition, a CRITICAL
severity for retry-eligible path, and escalation chain signal types.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_SIM_DRIVER = Path(__file__).resolve().parents[2] / "services" / "sim-driver"
_SCENARIO_PATH = _SIM_DRIVER / "scenarios" / "edge_cases.yaml"

# Import models from sim-driver without polluting sys.path
_spec = importlib.util.spec_from_file_location(
    "sim_driver_models",
    _SIM_DRIVER / "src" / "models.py",
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


def test_pydantic_validates_structure():
    """Scenario loads without validation errors."""
    scenario = _load_scenario()
    assert scenario.name == "edge_cases"


def test_at_least_two_false_positive_patients():
    """At least 2 patients have ONLY non-anomalous signals."""
    scenario = _load_scenario()
    fp_count = 0
    for patient in scenario.patients:
        if all(not s.anomalous for s in patient.signals):
            fp_count += 1
    assert fp_count >= 2, f"Only {fp_count} false-positive patients found"


def test_at_least_three_concurrent_sim_hours():
    """At least 3 patients share the same sim_hour (concurrent claim competition)."""
    scenario = _load_scenario()
    from collections import Counter

    hour_counts = Counter()
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous:
                hour_counts[signal.sim_hour] += 1
    max_concurrent = max(hour_counts.values()) if hour_counts else 0
    assert max_concurrent >= 3, f"Max concurrent anomalous signals at same sim_hour is {max_concurrent}, need >= 3"


def test_has_critical_severity_for_retry():
    """At least 1 patient has CRITICAL severity_hint (retry-eligible via persona config)."""
    scenario = _load_scenario()
    critical_count = 0
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.severity_hint == "CRITICAL":
                critical_count += 1
    assert critical_count >= 1, "No CRITICAL severity_hint found"


def test_has_urgent_non_glucose_spo2_for_escalation():
    """At least 1 patient has URGENT + non-glucose/spo2 signal type (escalation path)."""
    scenario = _load_scenario()
    found = False
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous and signal.severity_hint == "URGENT" and signal.type not in ("glucose", "spo2"):
                found = True
                break
    assert found, "No URGENT non-glucose/spo2 signal found for escalation path"


def test_has_high_or_no_severity_escalation():
    """At least 1 patient has anomalous=true with no severity_hint (HIGH/escalation path)."""
    scenario = _load_scenario()
    found = False
    for patient in scenario.patients:
        for signal in patient.signals:
            if signal.anomalous and signal.severity_hint is None:
                found = True
                break
    assert found, "No anomalous signal without severity_hint found for escalation path"


def test_no_duplicate_patient_ids():
    scenario = _load_scenario()
    ids = [p.patient_id for p in scenario.patients]
    assert len(ids) == len(set(ids)), f"Duplicate patient_ids: {len(ids) - len(set(ids))}"
