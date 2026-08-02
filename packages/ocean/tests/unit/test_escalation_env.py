"""Source-inspection tests for ESCALATION_ENABLED env control.

Verifies that docker-compose.yml and Taskfile.yml both reference
ESCALATION_ENABLED, and that the sim profile defaults it to false.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
TASKFILE = REPO_ROOT / "Taskfile.yml"


def test_compose_file_exists():
    assert COMPOSE.exists(), f"Expected docker-compose.yml at {COMPOSE}"


def test_taskfile_exists():
    assert TASKFILE.exists(), f"Expected Taskfile.yml at {TASKFILE}"


def test_escalation_enabled_in_compose():
    src = COMPOSE.read_text()
    assert "ESCALATION_ENABLED" in src, (
        "docker-compose.yml must define ESCALATION_ENABLED for control-plane"
    )


def test_escalation_enabled_in_taskfile():
    src = TASKFILE.read_text()
    assert "ESCALATION_ENABLED" in src, (
        "Taskfile.yml must reference ESCALATION_ENABLED"
    )


def test_escalation_disabled_in_sim_profile():
    """Sim profile sets ESCALATION_ENABLED=false to prevent escalation during simulation."""
    src = TASKFILE.read_text()
    # Find lines with ESCALATION_ENABLED and check one has 'false'
    lines = [line for line in src.splitlines() if "ESCALATION_ENABLED" in line]
    assert any("false" in line.lower() for line in lines), (
        "Taskfile.yml must set ESCALATION_ENABLED=false for sim profile"
    )
