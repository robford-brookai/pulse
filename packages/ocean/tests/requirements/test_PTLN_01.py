"""PTLN-01: Consolidated patient timeline view covers all entity tables.

Verifies the Alembic migration 0013 creates a patient_timeline view that
UNION ALLs all 8 entity tables into a consistent shape:
(patient_id, event_type, event_id, status, summary, created_at).

Uses source inspection — no Docker or live DB required.
"""

from __future__ import annotations

import pathlib

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
_MIGRATION = _ROOT / "infra" / "postgres" / "versions" / "0013_patient_timeline_view.py"

# All entity tables that must appear in the UNION ALL view
_ENTITY_TABLES = [
    "alerts",
    "tasks",
    "tickets",
    "fulfillments",
    "returns",
    "device_associations",
    "interactions",
    "signals",
]

# Required output columns for every SELECT in the UNION
_REQUIRED_COLUMNS = [
    "patient_id",
    "event_type",
    "event_id",
    "status",
    "summary",
    "created_at",
]


@pytest.fixture(scope="module")
def migration_source() -> str:
    """Read the migration file source."""
    assert _MIGRATION.exists(), f"Migration file not found: {_MIGRATION}"
    return _MIGRATION.read_text()


class TestPatientTimelineView:
    """Verify patient_timeline view definition in migration 0013."""

    def test_migration_exists(self):
        """Migration file 0013_patient_timeline_view.py must exist."""
        assert _MIGRATION.exists(), f"Expected migration at {_MIGRATION}"

    def test_creates_view(self, migration_source: str):
        """Migration must CREATE OR REPLACE VIEW patient_timeline."""
        assert "CREATE OR REPLACE VIEW patient_timeline" in migration_source

    @pytest.mark.parametrize("table", _ENTITY_TABLES)
    def test_union_includes_table(self, migration_source: str, table: str):
        """View must SELECT FROM each entity table."""
        assert f"FROM {table}" in migration_source, f"patient_timeline view missing FROM {table}"

    def test_union_all_count(self, migration_source: str):
        """View must have 7 UNION ALL clauses (8 tables = 7 unions)."""
        count = migration_source.count("UNION ALL")
        assert count == 7, f"Expected 7 UNION ALL, found {count}"

    @pytest.mark.parametrize("column", _REQUIRED_COLUMNS)
    def test_output_columns_present(self, migration_source: str, column: str):
        """Each required output column must appear as alias in SELECT clauses."""
        # event_type and event_id appear as aliases (AS event_type, AS event_id)
        if column in ("event_type", "event_id", "summary"):
            assert f"AS {column}" in migration_source, f"Missing AS {column} alias in view definition"
        else:
            # patient_id, status, created_at are direct column references
            assert column in migration_source

    def test_event_type_literals(self, migration_source: str):
        """Each SELECT must produce a distinct event_type literal."""
        expected_types = [
            "'alert'",
            "'task'",
            "'ticket'",
            "'fulfillment'",
            "'return'",
            "'device'",
            "'interaction'",
            "'signal'",
        ]
        for event_type in expected_types:
            assert event_type in migration_source, f"Missing event_type literal {event_type} in view"

    def test_downgrade_drops_view(self, migration_source: str):
        """Downgrade must DROP VIEW IF EXISTS patient_timeline."""
        assert "DROP VIEW IF EXISTS patient_timeline" in migration_source

    def test_summary_has_type_specific_content(self, migration_source: str):
        """Summary column should use type-specific fields, not generic placeholders."""
        # Alert summary uses alert_type and severity
        assert "alert_type" in migration_source
        assert "severity" in migration_source
        # Ticket summary uses human_id and category
        assert "human_id" in migration_source
        assert "category" in migration_source
        # Signal summary uses signal_type and value
        assert "signal_type" in migration_source
