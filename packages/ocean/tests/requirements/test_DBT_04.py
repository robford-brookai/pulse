"""DBT-04: Mart model computes MTTO (mean time to outreach: alert.created -> task.claimed)."""
from __future__ import annotations
from pathlib import Path

MTTO_FILE = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean" / "marts" / "ocean_mtto.sql"

def test_mtto_model_exists():
    assert MTTO_FILE.is_file()

def test_mtto_joins_alerts_and_tasks():
    content = MTTO_FILE.read_text()
    assert "ref('core_ocean_alerts')" in content
    assert "ref('core_ocean_tasks')" in content

def test_mtto_uses_correlation_id_join():
    content = MTTO_FILE.read_text()
    assert "correlation_id" in content

def test_mtto_computes_minutes_to_outreach():
    content = MTTO_FILE.read_text()
    assert "minutes_to_outreach" in content
    assert "DATEDIFF" in content

def test_mtto_filters_alert_created():
    content = MTTO_FILE.read_text()
    assert "alert.created" in content

def test_mtto_filters_task_claimed():
    content = MTTO_FILE.read_text()
    assert "task.claimed" in content

def test_mtto_aggregates_by_day():
    content = MTTO_FILE.read_text()
    assert "DATE_TRUNC" in content
    assert "metric_date" in content
