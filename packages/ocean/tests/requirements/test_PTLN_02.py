"""PTLN-02: Hasura metadata tracks patient_timeline view for GraphQL access.

Verifies apply_metadata.py includes patient_timeline in ALL_TABLES and that
the migration file exists with the expected view columns. Uses source
inspection -- no Docker or live Hasura required.
"""

from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).parents[2]
_APPLY_METADATA = _ROOT / "infra" / "hasura" / "apply_metadata.py"
_MIGRATION = _ROOT / "infra" / "postgres" / "versions" / "0013_patient_timeline_view.py"

# Expected output columns of the patient_timeline view
_VIEW_COLUMNS = [
    "patient_id",
    "event_type",
    "event_id",
    "status",
    "summary",
    "created_at",
]


class TestPatientTimelineHasura:
    """Verify Hasura metadata configuration for patient_timeline view."""

    def test_apply_metadata_includes_patient_timeline(self):
        """patient_timeline must be in ALL_TABLES list."""
        source = _APPLY_METADATA.read_text()
        assert '"patient_timeline"' in source or "'patient_timeline'" in source, (
            "patient_timeline not found in apply_metadata.py ALL_TABLES"
        )

    def test_pg_track_table_call_exists(self):
        """apply_metadata.py must contain pg_track_table call that tracks all tables."""
        source = _APPLY_METADATA.read_text()
        assert "pg_track_table" in source, "No pg_track_table call found in apply_metadata.py"

    def test_migration_file_exists(self):
        """Migration 0013 must exist for the view patient_timeline."""
        assert _MIGRATION.exists(), f"Migration file not found: {_MIGRATION}"

    def test_view_columns_in_migration(self):
        """Migration must produce all expected output columns."""
        source = _MIGRATION.read_text()
        for col in _VIEW_COLUMNS:
            if col in ("event_type", "event_id", "summary"):
                assert f"AS {col}" in source, f"Missing AS {col} alias in migration view definition"
            else:
                assert col in source, f"Missing column {col} in migration view definition"

    def test_no_relationships_for_view(self):
        """patient_timeline is a flat view -- no relationships should reference it."""
        source = _APPLY_METADATA.read_text()
        # Should not appear in ARRAY_RELATIONSHIPS or OBJECT_RELATIONSHIPS tuples
        # (it can appear in ALL_TABLES but not as a relationship endpoint)
        arr_idx = source.find("ARRAY_RELATIONSHIPS")
        obj_idx = source.find("OBJECT_RELATIONSHIPS")
        if arr_idx != -1 and obj_idx != -1:
            relationships_section = source[arr_idx:]
            # Count occurrences in relationship definitions (excluding ALL_TABLES)
            tables_end = source.find("ARRAY_RELATIONSHIPS")
            rel_source = source[tables_end:]
            # patient_timeline should NOT appear in relationship tuples
            assert "patient_timeline" not in rel_source, "patient_timeline should not have relationships defined"
