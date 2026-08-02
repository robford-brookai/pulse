"""DBT-02: stg_ocean_events extracts typed columns from VARIANT JSON with event_type filtering."""

from __future__ import annotations

from pathlib import Path

STG_FILE = (
    Path(__file__).resolve().parents[2]
    / ".repos"
    / "streamline"
    / "dbt_project"
    / "models"
    / "ocean"
    / "input"
    / "stg_ocean_events.sql"
)


def test_stg_ocean_events_exists():
    assert STG_FILE.is_file()


def test_extracts_event_id():
    content = STG_FILE.read_text()
    assert "data:event_id::VARCHAR" in content


def test_extracts_event_type():
    content = STG_FILE.read_text()
    assert "data:event_type::VARCHAR" in content


def test_extracts_event_timestamp():
    content = STG_FILE.read_text()
    assert "data:timestamp::TIMESTAMP_NTZ" in content


def test_extracts_correlation_id():
    content = STG_FILE.read_text()
    assert "data:correlation_id::VARCHAR" in content


def test_payload_kept_as_variant():
    content = STG_FILE.read_text()
    # payload should NOT be cast -- kept as VARIANT for core models
    assert "data:payload" in content
    # Ensure no cast on payload (should be just "data:payload" with alias, not "data:payload::VARCHAR")
    lines = [line.strip() for line in content.splitlines() if "data:payload" in line]
    for line in lines:
        assert "::VARCHAR" not in line or "payload" not in line.split("::VARCHAR")[0].split(",")[-1]


def test_references_ocean_raw_source():
    content = STG_FILE.read_text()
    assert "source('ocean_raw', 'events')" in content


def test_materialized_as_view():
    content = STG_FILE.read_text()
    assert "materialized='view'" in content or 'materialized="view"' in content
