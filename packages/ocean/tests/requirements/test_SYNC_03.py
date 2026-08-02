"""SYNC-03: Snowflake DDL provisions OCEAN_RAW/CORE/MARTS schemas with RBAC isolation."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_DDL = _ROOT / ".repos" / "streamline" / "snowflake" / "ddl" / "06_ocean_schemas.sql"


def _ddl() -> str:
    return _DDL.read_text()


def test_ocean_schemas_created():
    ddl = _ddl()
    for schema in ("OCEAN_RAW", "OCEAN_CORE", "OCEAN_MARTS"):
        assert f"CREATE SCHEMA IF NOT EXISTS STREAMLINE.{schema}" in ddl, f"Missing CREATE SCHEMA for {schema}"


def test_events_table_created():
    ddl = _ddl()
    assert "CREATE TABLE IF NOT EXISTS STREAMLINE.OCEAN_RAW.EVENTS" in ddl
    assert "VARIANT" in ddl
    assert "_topic" in ddl


def test_rbac_roles_created():
    ddl = _ddl()
    assert "CREATE ROLE IF NOT EXISTS OCEAN_WRITER" in ddl
    assert "CREATE ROLE IF NOT EXISTS OCEAN_ANALYST" in ddl


def test_writer_grants_present():
    ddl = _ddl()
    assert "GRANT INSERT, SELECT ON TABLE STREAMLINE.OCEAN_RAW.EVENTS TO ROLE OCEAN_WRITER" in ddl


def test_phi_schemas_not_granted_to_analyst():
    """OCEAN_ANALYST must NOT have grants on ZCC_* or IMPILO_* schemas — HIPAA boundary."""
    ddl = _ddl()
    # Find where OCEAN_ANALYST grants begin (after OCEAN_WRITER section)
    analyst_section_start = ddl.find("-- Analyst grants")
    assert analyst_section_start != -1, "DDL missing '-- Analyst grants' comment"
    analyst_section = ddl[analyst_section_start:]
    assert "ZCC_" not in analyst_section, "OCEAN_ANALYST must not have grants on ZCC_* schemas"
    assert "IMPILO_" not in analyst_section, "OCEAN_ANALYST must not have grants on IMPILO_* schemas"
