"""DBT-06: Mart model computes ticket resolution time by priority."""

from __future__ import annotations

from pathlib import Path

TR_FILE = (
    Path(__file__).resolve().parents[2]
    / ".repos"
    / "streamline"
    / "dbt_project"
    / "models"
    / "ocean"
    / "marts"
    / "ocean_ticket_resolution.sql"
)


def test_ticket_resolution_model_exists():
    assert TR_FILE.is_file()


def test_computes_resolution_time():
    content = TR_FILE.read_text()
    assert "resolution_minutes" in content
    assert "DATEDIFF" in content


def test_groups_by_priority():
    content = TR_FILE.read_text()
    assert "priority" in content


def test_filters_ticket_created_and_resolved():
    content = TR_FILE.read_text()
    assert "ticket.created" in content
    assert "ticket.resolved" in content


def test_aggregates_by_day():
    content = TR_FILE.read_text()
    assert "metric_date" in content
