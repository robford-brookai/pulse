"""Source-inspection tests for control-plane outcome publishing.

Verifies services/control-plane/src/handlers/outcomes.py contains
the expected function signatures and topic references without
importing the module (avoids heavy service dependencies).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "control-plane" / "src" / "handlers" / "outcomes.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected source file at {SOURCE}"


def test_build_outcome_event_signature():
    src = _source()
    assert "def build_outcome_event(" in src


def test_handle_alert_resolved_signature():
    src = _source()
    assert "async def handle_alert_resolved(" in src


def test_handle_task_completed_signature():
    src = _source()
    assert "async def handle_task_completed(" in src


def test_handle_call_completed_signature():
    src = _source()
    assert "async def handle_call_completed(" in src


def test_handle_call_missed_signature():
    src = _source()
    assert "async def handle_call_missed(" in src


def test_publishes_to_outcomes_topic():
    src = _source()
    assert '"ocean.outcomes"' in src, "outcomes.py must publish to ocean.outcomes topic"
