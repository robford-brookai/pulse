"""Source-inspection tests for the escalation engine.

Verifies services/control-plane/src/escalation.py contains
all expected function signatures without importing the module.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "control-plane" / "src" / "escalation.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected source file at {SOURCE}"


def test_find_escalation_candidates_signature():
    src = _source()
    assert "async def find_escalation_candidates(" in src


def test_check_and_escalate_signature():
    src = _source()
    assert "async def check_and_escalate(" in src


def test_insert_escalation_state_signature():
    src = _source()
    assert "async def insert_escalation_state(" in src


def test_remove_escalation_state_signature():
    src = _source()
    assert "async def remove_escalation_state(" in src


def test_rehydrate_and_catch_up_signature():
    src = _source()
    assert "async def rehydrate_and_catch_up(" in src


def test_run_escalation_poller_signature():
    src = _source()
    assert "async def run_escalation_poller(" in src
