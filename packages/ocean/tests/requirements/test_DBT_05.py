"""DBT-05: Mart model computes false-positive rate."""
from __future__ import annotations
from pathlib import Path

FP_FILE = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean" / "marts" / "ocean_false_positive_rate.sql"

def test_false_positive_model_exists():
    assert FP_FILE.is_file()

def test_references_core_alerts():
    content = FP_FILE.read_text()
    assert "ref('core_ocean_alerts')" in content

def test_filters_alert_resolved():
    content = FP_FILE.read_text()
    assert "alert.resolved" in content

def test_checks_false_positive_resolution():
    content = FP_FILE.read_text()
    assert "false_positive" in content

def test_computes_rate():
    content = FP_FILE.read_text()
    assert "false_positive_rate" in content
    assert "total_resolved" in content
