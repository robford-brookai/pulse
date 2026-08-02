"""DBT-07: Mart model computes call completion rate by disposition."""
from __future__ import annotations
from pathlib import Path

CC_FILE = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean" / "marts" / "ocean_call_completion.sql"

def test_call_completion_model_exists():
    assert CC_FILE.is_file()

def test_references_outcomes():
    content = CC_FILE.read_text()
    assert "ref('core_ocean_outcomes')" in content

def test_filters_call_events():
    content = CC_FILE.read_text()
    assert "call.completed" in content
    assert "call.missed" in content

def test_computes_completion_rate():
    content = CC_FILE.read_text()
    assert "completion_rate" in content

def test_groups_by_disposition():
    content = CC_FILE.read_text()
    assert "disposition" in content
