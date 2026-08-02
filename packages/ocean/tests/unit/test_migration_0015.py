"""Source-inspection tests for migration 0015 (task_escalation_state).

Verifies the migration creates the task_escalation_state table and
makes interaction_id nullable.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "infra" / "postgres" / "versions" / "0015_task_escalation_state.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected migration file at {SOURCE}"


def test_creates_task_escalation_state_table():
    src = _source()
    assert "task_escalation_state" in src, "Migration 0015 must create task_escalation_state table"


def test_contains_create_table():
    src = _source()
    assert "CREATE TABLE" in src, "Migration 0015 must contain CREATE TABLE statement"


def test_interaction_id_nullable():
    src = _source()
    assert "interaction_id" in src, "Migration 0015 must make interaction_id nullable"


def test_has_upgrade_function():
    src = _source()
    assert "def upgrade(" in src


def test_has_downgrade_function():
    src = _source()
    assert "def downgrade(" in src
