"""DEMO-02: Pilot demo scenario validation.

Verifies pilot_demo.yaml has 10 patients with correct severity distribution,
staggered sim_hours, proper patient_id pattern, and compression_ratio.
Also validates Taskfile.yml demo task configuration.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = REPO_ROOT / "services" / "sim-driver" / "scenarios" / "pilot_demo.yaml"
TASKFILE_PATH = REPO_ROOT / "Taskfile.yml"


@pytest.fixture
def scenario():
    """Load pilot_demo.yaml."""
    with open(SCENARIO_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def taskfile_content():
    """Read Taskfile.yml as text."""
    return TASKFILE_PATH.read_text()


# ---------------------------------------------------------------------------
# Scenario validation
# ---------------------------------------------------------------------------


def test_scenario_has_10_patients(scenario):
    """pilot_demo.yaml must have exactly 10 patients."""
    assert len(scenario["patients"]) == 10


def test_severity_distribution(scenario):
    """At least 3 CRITICAL, 2 URGENT, 2 HIGH patients."""
    severities = {"CRITICAL": 0, "URGENT": 0, "HIGH": 0}
    for patient in scenario["patients"]:
        for signal in patient["signals"]:
            hint = signal.get("severity_hint")
            if hint in severities:
                severities[hint] += 1
                break  # Count each patient once by their first anomalous signal

    assert severities["CRITICAL"] >= 3, f"CRITICAL: {severities['CRITICAL']} < 3"
    assert severities["URGENT"] >= 2, f"URGENT: {severities['URGENT']} < 2"
    assert severities["HIGH"] >= 2, f"HIGH: {severities['HIGH']} < 2"


def test_sim_hours_unique_per_first_signal(scenario):
    """No two patients share the same sim_hour for their first signal."""
    first_hours = []
    for patient in scenario["patients"]:
        if patient["signals"]:
            first_hours.append(patient["signals"][0]["sim_hour"])
    assert len(first_hours) == len(set(first_hours)), "Duplicate first sim_hours found"


def test_sim_hours_span(scenario):
    """sim_hours span from approximately 0.05 to 0.50."""
    first_hours = [p["signals"][0]["sim_hour"] for p in scenario["patients"]]
    assert min(first_hours) <= 0.06, f"Min sim_hour {min(first_hours)} > 0.06"
    assert max(first_hours) >= 0.35, f"Max sim_hour {max(first_hours)} < 0.35"


def test_compression_ratio(scenario):
    """compression_ratio must be 960."""
    assert scenario["compression_ratio"] == 960


def test_patient_id_pattern(scenario):
    """All patient_ids must match sim-pt-demo-NNN."""
    pattern = re.compile(r"^sim-pt-demo-\d{3}$")
    for patient in scenario["patients"]:
        pid = patient["patient_id"]
        assert pattern.match(pid), f"Bad patient_id: {pid}"


def test_patient_id_range(scenario):
    """Patient IDs must span 001 to 010."""
    numbers = sorted(int(p["patient_id"].split("-")[-1]) for p in scenario["patients"])
    assert numbers[0] == 1
    assert numbers[-1] == 10
    assert len(numbers) == 10


# ---------------------------------------------------------------------------
# Taskfile validation
# ---------------------------------------------------------------------------


def test_taskfile_has_demo_task(taskfile_content):
    """Taskfile.yml must contain demo: task definition."""
    assert "demo:" in taskfile_content


def test_taskfile_escalation_enabled(taskfile_content):
    """Taskfile demo task sets ESCALATION_ENABLED=true."""
    assert 'ESCALATION_ENABLED: "true"' in taskfile_content


def test_taskfile_escalation_timeout_critical(taskfile_content):
    """Taskfile demo task sets ESCALATION_TIMEOUT_CRITICAL=30."""
    assert 'ESCALATION_TIMEOUT_CRITICAL: "30"' in taskfile_content
