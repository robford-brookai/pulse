"""DBT-09: dbt test asserts Ocean mart models contain no columns from PHI-adjacent source tables."""

from __future__ import annotations

from pathlib import Path

PHI_TEST_FILE = (
    Path(__file__).resolve().parents[2]
    / ".repos"
    / "streamline"
    / "dbt_project"
    / "tests"
    / "ocean"
    / "assert_ocean_no_phi_sources.sql"
)
MART_DIR = Path(__file__).resolve().parents[2] / ".repos" / "streamline" / "dbt_project" / "models" / "ocean" / "marts"


def test_phi_isolation_test_exists():
    assert PHI_TEST_FILE.is_file(), f"Missing: {PHI_TEST_FILE}"


def test_phi_test_checks_phi_schemas():
    content = PHI_TEST_FILE.read_text()
    for schema in ["ZCC_RAW", "ZCC_CORE", "ZCC_MARTS", "IMPILO_RAW", "IMPILO_CORE", "IMPILO_MARTS"]:
        assert schema in content, f"PHI test missing schema check: {schema}"


def test_phi_test_inspects_ocean_marts():
    content = PHI_TEST_FILE.read_text()
    assert "OCEAN_MARTS" in content


def test_mart_models_only_reference_ocean_models():
    """Mart SQL files must only ref() ocean models, never source() from PHI schemas."""
    mart_files = list(MART_DIR.glob("ocean_*.sql"))
    assert len(mart_files) >= 4, f"Expected at least 4 mart models, found {len(mart_files)}"
    phi_keywords = ["zcc_raw", "impilo_raw", "zcc_core", "impilo_core", "stg_zcc", "stg_impilo"]
    for f in mart_files:
        content = f.read_text().lower()
        for kw in phi_keywords:
            assert kw not in content, f"{f.name} references PHI-adjacent: {kw}"
