"""DBT-01: Streamline dbt project has ocean/ model layer with stg, core, and marts sublayers."""

from __future__ import annotations

from pathlib import Path

STREAMLINE_MODELS = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean"


def test_ocean_model_directory_exists():
    assert STREAMLINE_MODELS.is_dir(), f"Missing: {STREAMLINE_MODELS}"


def test_ocean_input_sublayer_exists():
    assert (STREAMLINE_MODELS / "input").is_dir()


def test_ocean_core_sublayer_exists():
    assert (STREAMLINE_MODELS / "core").is_dir()


def test_ocean_marts_sublayer_exists():
    assert (STREAMLINE_MODELS / "marts").is_dir()


def test_ocean_sources_yml_exists():
    assert (STREAMLINE_MODELS / "_ocean_sources.yml").is_file()


def test_dbt_project_yml_has_ocean_config():
    dbt_project = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "dbt_project.yml"
    content = dbt_project.read_text()
    assert "ocean:" in content
    assert "+schema: ocean_raw" in content
    assert "+schema: ocean_core" in content
    assert "+schema: ocean_marts" in content
