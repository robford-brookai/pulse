"""Unit tests for BaseTransformer protocol and AlertsTransformer."""
from __future__ import annotations

import sys
import pathlib

# The transformer module lives under services/mongodb-connector/src,
# so we add its parent to sys.path.
_SRC = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector" / "src"
sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from transformer import AlertsTransformer, BaseTransformer  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_change_doc(
    operation_type: str = "insert",
    full_document: dict | None = None,
    *,
    include_full_doc: bool = True,
) -> dict:
    """Build a minimal MongoDB change-stream document."""
    doc: dict = {
        "operationType": operation_type,
        "ns": {"db": "carenexus", "coll": "alerts"},
        "documentKey": {"_id": "abc123"},
    }
    if include_full_doc and full_document is not None:
        doc["fullDocument"] = full_document
    elif include_full_doc and operation_type != "delete":
        doc["fullDocument"] = {
            "patientId": "patient-001",
            "status": "active",
            "type": "glucose_high",
            "clearedAt": "2026-03-18T12:00:00Z",
            "vitalType": "glucose",
        }
    else:
        doc["fullDocument"] = None
    return doc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAlertsTransformer:
    """AlertsTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = AlertsTransformer()

    def test_insert_operation(self) -> None:
        """Insert with full fullDocument returns correct payload with all features."""
        change_doc = _make_change_doc("insert")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "alerts"
        assert result["patient_id"] == "patient-001"
        assert result["operation_type"] == "insert"
        assert result["features"]["alert_status"] == "active"
        assert result["features"]["alert_type"] == "glucose_high"
        assert result["features"]["cleared_at"] == "2026-03-18T12:00:00Z"
        assert result["features"]["vital_type"] == "glucose"

    def test_update_operation(self) -> None:
        """Update operation returns payload with operation_type='update'."""
        change_doc = _make_change_doc("update")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["operation_type"] == "update"
        assert result["patient_id"] == "patient-001"

    def test_delete_returns_none(self) -> None:
        """Delete operation with no fullDocument returns None."""
        change_doc = _make_change_doc("delete", include_full_doc=False)
        result = self.transformer.transform(change_doc)

        assert result is None

    def test_missing_patient_id_returns_none(self) -> None:
        """fullDocument without patientId returns None (defensive guard)."""
        change_doc = _make_change_doc(
            "insert",
            full_document={
                "status": "active",
                "type": "glucose_high",
            },
        )
        result = self.transformer.transform(change_doc)

        assert result is None

    def test_partial_features(self) -> None:
        """fullDocument with only some fields → missing features are None."""
        change_doc = _make_change_doc(
            "insert",
            full_document={
                "patientId": "patient-002",
                "status": "resolved",
                # type, clearedAt, vitalType all missing
            },
        )
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["patient_id"] == "patient-002"
        assert result["features"]["alert_status"] == "resolved"
        assert result["features"]["alert_type"] is None
        assert result["features"]["cleared_at"] is None
        assert result["features"]["vital_type"] is None

    def test_no_phi_in_output(self) -> None:
        """Output feature keys must not overlap with BaseEvent _PHI_FIELD_NAMES."""
        from ocean_events.base import _PHI_FIELD_NAMES

        change_doc = _make_change_doc("insert")
        result = self.transformer.transform(change_doc)

        assert result is not None
        feature_keys = set(result["features"].keys())
        overlap = feature_keys & _PHI_FIELD_NAMES
        assert not overlap, f"Feature keys overlap with PHI fields: {overlap}"

        # Also check top-level keys
        top_keys = set(result.keys())
        top_overlap = top_keys & _PHI_FIELD_NAMES
        assert not top_overlap, f"Top-level keys overlap with PHI fields: {top_overlap}"

    def test_conforms_to_protocol(self) -> None:
        """AlertsTransformer satisfies BaseTransformer protocol."""
        transformer = AlertsTransformer()
        assert isinstance(transformer, BaseTransformer)
