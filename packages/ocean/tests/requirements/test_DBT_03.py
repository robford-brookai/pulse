"""DBT-03: Core models exist: core_ocean_alerts, core_ocean_outcomes, core_ocean_tickets, core_ocean_tasks."""
from __future__ import annotations
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean" / "core"

EXPECTED_MODELS = [
    "core_ocean_alerts.sql",
    "core_ocean_tasks.sql",
    "core_ocean_tickets.sql",
    "core_ocean_outcomes.sql",
]

def test_core_directory_exists():
    assert CORE_DIR.is_dir()

def test_all_core_models_exist():
    for model in EXPECTED_MODELS:
        assert (CORE_DIR / model).is_file(), f"Missing: {model}"

def test_core_yml_exists():
    assert (CORE_DIR / "_ocean_core.yml").is_file()

def test_core_models_reference_staging():
    for model in EXPECTED_MODELS:
        content = (CORE_DIR / model).read_text()
        assert "ref('stg_ocean_events')" in content, f"{model} missing ref to stg_ocean_events"

def test_core_models_use_incremental():
    for model in EXPECTED_MODELS:
        content = (CORE_DIR / model).read_text()
        assert "incremental" in content, f"{model} not incremental"
        assert "unique_key='event_id'" in content, f"{model} missing unique_key"
