"""Source-inspection tests for ticket resolution dual-publish.

Verifies services/control-plane/src/handlers/tickets.py publishes
outcome.recorded events to ocean.outcomes on ticket resolution.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "control-plane" / "src" / "handlers" / "tickets.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected source file at {SOURCE}"


def test_publishes_to_outcomes_topic():
    src = _source()
    assert '"ocean.outcomes"' in src, "tickets.py must dual-publish to ocean.outcomes"


def test_outcome_recorded_event_type():
    src = _source()
    assert "outcome.recorded" in src or "build_outcome_event" in src, "tickets.py must produce outcome.recorded events"


def test_uses_build_outcome_event():
    src = _source()
    assert "build_outcome_event" in src, "tickets.py must use build_outcome_event from outcomes module"
