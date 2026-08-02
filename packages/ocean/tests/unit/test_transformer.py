"""Unit tests for BaseTransformer protocol and all collection transformers."""

from __future__ import annotations

import pathlib
import sys

# The transformer module lives under services/mongodb-connector/src,
# so we add its parent to sys.path.
_SRC = pathlib.Path(__file__).resolve().parents[2] / "services" / "mongodb-connector" / "src"
sys.path.insert(0, str(_SRC))


from ocean_events.base import _PHI_FIELD_NAMES
from transformer import (
    TRANSFORMER_REGISTRY,
    ActivityTransformer,
    AlertsTransformer,
    BaseTransformer,
    ChatRoomsTransformer,
    DashboardDetailsTransformer,
    MonitoringTimeRawTransformer,
    PatientCarePlansTransformer,
    PatientNoteTransformer,
    PersonaTransformer,
    ProviderProtocolsTransformer,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_change_doc(
    operation_type: str = "insert",
    full_document: dict | None = None,
    *,
    include_full_doc: bool = True,
    collection: str = "alerts",
) -> dict:
    """Build a minimal MongoDB change-stream document."""
    doc: dict = {
        "operationType": operation_type,
        "ns": {"db": "carenexus", "coll": collection},
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


def _assert_phi_guard(result: dict) -> None:
    """Assert no PHI field names appear in feature keys or top-level keys."""
    feature_keys = set(result["features"].keys())
    overlap = feature_keys & _PHI_FIELD_NAMES
    assert not overlap, f"Feature keys overlap with PHI fields: {overlap}"
    top_keys = set(result.keys())
    top_overlap = top_keys & _PHI_FIELD_NAMES
    assert not top_overlap, f"Top-level keys overlap with PHI fields: {top_overlap}"


# ---------------------------------------------------------------------------
# AlertsTransformer Tests
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
        change_doc = _make_change_doc("insert")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        """AlertsTransformer satisfies BaseTransformer protocol."""
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# ChatRoomsTransformer Tests
# ---------------------------------------------------------------------------


class TestChatRoomsTransformer:
    """ChatRoomsTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = ChatRoomsTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "type": "expert",
            "subscribers": [
                {"personaID": "patient-100", "name": "Alice"},
                {"personaID": "patient-200"},
            ],
            "unread_message_count": 5,
            "latest_message_timestamp": "2026-03-18T14:00:00Z",
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="chatRooms")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "chatRooms"
        assert result["patient_id"] == "patient-100"
        assert result["operation_type"] == "insert"
        assert result["features"]["unread_message_count"] == 5
        assert result["features"]["latest_message_timestamp"] == "2026-03-18T14:00:00Z"

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="chatRooms")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        """Subscribers with no personaID → None."""
        doc = self._full_doc(subscribers=[{"name": "NoID"}])
        change_doc = _make_change_doc("insert", full_document=doc, collection="chatRooms")
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        doc = self._full_doc()
        del doc["unread_message_count"]
        del doc["latest_message_timestamp"]
        change_doc = _make_change_doc("insert", full_document=doc, collection="chatRooms")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["unread_message_count"] is None
        assert result["features"]["latest_message_timestamp"] is None

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="chatRooms")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)

    def test_non_expert_type_returns_none(self) -> None:
        """Non-expert chat rooms are filtered out."""
        doc = self._full_doc(type="patient")
        change_doc = _make_change_doc("insert", full_document=doc, collection="chatRooms")
        assert self.transformer.transform(change_doc) is None

    def test_expert_type_case_insensitive(self) -> None:
        """Type check is case-insensitive."""
        doc = self._full_doc(type="Expert")
        change_doc = _make_change_doc("insert", full_document=doc, collection="chatRooms")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["patient_id"] == "patient-100"

    def test_empty_subscribers_returns_none(self) -> None:
        doc = self._full_doc(subscribers=[])
        change_doc = _make_change_doc("insert", full_document=doc, collection="chatRooms")
        assert self.transformer.transform(change_doc) is None


# ---------------------------------------------------------------------------
# ActivityTransformer Tests
# ---------------------------------------------------------------------------


class TestActivityTransformer:
    """ActivityTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = ActivityTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "persona_id": "patient-300",
            "lastReadingAt": "2026-03-18T10:00:00Z",
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="activity")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "activity"
        assert result["patient_id"] == "patient-300"
        assert result["features"]["last_reading_at"] == "2026-03-18T10:00:00Z"
        assert result["features"]["readings_count_current"] == 1

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="activity")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"lastReadingAt": "x"}, collection="activity")
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"persona_id": "p1"}, collection="activity")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["last_reading_at"] is None
        assert result["features"]["readings_count_current"] == 1

    def test_snake_case_fallback(self) -> None:
        """Falls back to snake_case field name."""
        doc = {"persona_id": "p2", "last_reading_at": "2026-01-01T00:00:00Z"}
        change_doc = _make_change_doc("insert", full_document=doc, collection="activity")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["last_reading_at"] == "2026-01-01T00:00:00Z"

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="activity")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# ProviderProtocolsTransformer Tests
# ---------------------------------------------------------------------------


class TestProviderProtocolsTransformer:
    """ProviderProtocolsTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = ProviderProtocolsTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "persona_id": "patient-400",
            "adherenceRate": 0.85,
            "missedReadingsPeriod": 3,
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="provider_protocols")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "provider_protocols"
        assert result["patient_id"] == "patient-400"
        assert result["features"]["protocol_adherence_rate"] == 0.85
        assert result["features"]["missed_readings_period"] == 3

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="provider_protocols")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"adherenceRate": 0.5}, collection="provider_protocols")
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"persona_id": "p1"}, collection="provider_protocols")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["protocol_adherence_rate"] is None
        assert result["features"]["missed_readings_period"] is None

    def test_adherence_rate_string_conversion(self) -> None:
        """String adherence rate is converted to float."""
        doc = self._full_doc(adherenceRate="0.75")
        change_doc = _make_change_doc("insert", full_document=doc, collection="provider_protocols")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["protocol_adherence_rate"] == 0.75

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="provider_protocols")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# PatientCarePlansTransformer Tests
# ---------------------------------------------------------------------------


class TestPatientCarePlansTransformer:
    """PatientCarePlansTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = PatientCarePlansTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc: dict = {
            "persona_id": "patient-500",
            "problem_list": {"items": ["hypertension"], "updated_at": "2026-01-01"},
            "current_medications": {"items": ["metformin"], "updated_at": "2026-02-01"},
            "allergies": {"items": ["penicillin"], "reviewed_at": "2026-03-01"},
            "preventative_care": {},
            "psychosocial_assessment": None,
            "care_teams": {"members": ["Dr. Smith"], "updated_at": "2026-03-15"},
            "ccmChartReviewedAt": "2026-03-10T00:00:00Z",
            "followUpDueTodayOrOverdue": True,
            "condition_specific_care_plans": [
                {"name": "Diabetes", "updated_at": "2026-03-18"},
            ],
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="patient_care_plans")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "patient_care_plans"
        assert result["patient_id"] == "patient-500"
        # problem_list, current_medications, allergies, care_teams are non-empty (4)
        # preventative_care is empty dict (falsy but truthy in Python — actually {} is truthy!)
        # Actually {} is falsy? No, {} is falsy. Wait: bool({}) is False. So preventative_care={} → falsy → not counted.
        # psychosocial_assessment is None → not counted.
        # So count = 4 (problem_list, current_medications, allergies, care_teams)
        # Actually wait — {} is falsy in Python? Let me check: bool({}) == False. Yes.
        # But preventative_care: {} — empty dict is falsy. So not counted.
        assert result["features"]["care_plan_count"] == 4
        # Latest timestamp: "2026-03-18" from condition_specific_care_plans
        assert result["features"]["care_plan_last_updated"] == "2026-03-18"
        assert result["features"]["ccm_chart_reviewed_at"] == "2026-03-10T00:00:00Z"
        assert result["features"]["follow_up_due_today_or_overdue"] is True

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="patient_care_plans")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        change_doc = _make_change_doc(
            "insert", full_document={"problem_list": {"items": []}}, collection="patient_care_plans"
        )
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        """Only persona_id present — all features are None/0."""
        change_doc = _make_change_doc("insert", full_document={"persona_id": "p1"}, collection="patient_care_plans")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["care_plan_count"] == 0
        assert result["features"]["care_plan_last_updated"] is None
        assert result["features"]["ccm_chart_reviewed_at"] is None
        assert result["features"]["follow_up_due_today_or_overdue"] is None

    def test_all_six_sections_counted(self) -> None:
        """All 6 sections non-empty → count = 6."""
        doc: dict = {
            "persona_id": "p1",
            "problem_list": {"items": ["a"]},
            "current_medications": {"items": ["b"]},
            "allergies": {"items": ["c"]},
            "preventative_care": {"items": ["d"]},
            "psychosocial_assessment": {"items": ["e"]},
            "care_teams": {"members": ["f"]},
        }
        change_doc = _make_change_doc("insert", full_document=doc, collection="patient_care_plans")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["care_plan_count"] == 6

    def test_condition_specific_plans_contribute_to_latest(self) -> None:
        """condition_specific_care_plans entries contribute to care_plan_last_updated."""
        doc: dict = {
            "persona_id": "p1",
            "condition_specific_care_plans": [
                {"name": "A", "updated_at": "2020-01-01"},
                {"name": "B", "reviewed_at": "2099-12-31"},
            ],
        }
        change_doc = _make_change_doc("insert", full_document=doc, collection="patient_care_plans")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["care_plan_last_updated"] == "2099-12-31"

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="patient_care_plans")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# PatientNoteTransformer Tests
# ---------------------------------------------------------------------------


class TestPatientNoteTransformer:
    """PatientNoteTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = PatientNoteTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "persona_id": "patient-600",
            "is_interaction": True,
            "pendingEmrNotes": 2,
            "last_nurse_interaction_at": "2026-03-18T09:00:00Z",
            "last_contact_at": "2026-03-17T15:00:00Z",
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="patient_note")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "patient_note"
        assert result["patient_id"] == "patient-600"
        assert result["features"]["pending_emr_notes"] == 2
        assert result["features"]["last_nurse_interaction_at"] == "2026-03-18T09:00:00Z"
        assert result["features"]["last_contact_at"] == "2026-03-17T15:00:00Z"

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="patient_note")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"is_interaction": True}, collection="patient_note")
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        doc = {"persona_id": "p1", "is_interaction": True}
        change_doc = _make_change_doc("insert", full_document=doc, collection="patient_note")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["pending_emr_notes"] is None
        assert result["features"]["last_nurse_interaction_at"] is None
        assert result["features"]["last_contact_at"] is None

    def test_non_interaction_note_returns_none(self) -> None:
        """Notes without is_interaction or interaction field are skipped."""
        doc = {"persona_id": "p1", "pendingEmrNotes": 1}
        change_doc = _make_change_doc("insert", full_document=doc, collection="patient_note")
        assert self.transformer.transform(change_doc) is None

    def test_interaction_field_alternative(self) -> None:
        """'interaction' field also marks a note as an interaction."""
        doc = {"persona_id": "p1", "interaction": True, "pendingEmrNotes": 3}
        change_doc = _make_change_doc("insert", full_document=doc, collection="patient_note")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["pending_emr_notes"] == 3

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="patient_note")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# MonitoringTimeRawTransformer Tests
# ---------------------------------------------------------------------------


class TestMonitoringTimeRawTransformer:
    """MonitoringTimeRawTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = MonitoringTimeRawTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "persona_id": "patient-700",
            "lastPocarOpenedAt": "2026-03-18T08:00:00Z",
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="monitoring_time_raw")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "monitoring_time_raw"
        assert result["patient_id"] == "patient-700"
        assert result["features"]["last_pocar_opened_at"] == "2026-03-18T08:00:00Z"

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="monitoring_time_raw")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        change_doc = _make_change_doc(
            "insert", full_document={"lastPocarOpenedAt": "x"}, collection="monitoring_time_raw"
        )
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"persona_id": "p1"}, collection="monitoring_time_raw")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["last_pocar_opened_at"] is None

    def test_fallback_to_later_candidate(self) -> None:
        """Falls back through timestamp candidates in order."""
        doc = {"persona_id": "p1", "updatedAt": "2026-02-01T00:00:00Z"}
        change_doc = _make_change_doc("insert", full_document=doc, collection="monitoring_time_raw")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["last_pocar_opened_at"] == "2026-02-01T00:00:00Z"

    def test_first_candidate_wins(self) -> None:
        """First matching candidate takes priority over later ones."""
        doc = {
            "persona_id": "p1",
            "lastPocarOpenedAt": "FIRST",
            "updatedAt": "SECOND",
            "createdAt": "THIRD",
        }
        change_doc = _make_change_doc("insert", full_document=doc, collection="monitoring_time_raw")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["last_pocar_opened_at"] == "FIRST"

    def test_last_candidate_createdAt(self) -> None:
        """createdAt is the last resort candidate."""
        doc = {"persona_id": "p1", "created_at": "2025-01-01"}
        change_doc = _make_change_doc("insert", full_document=doc, collection="monitoring_time_raw")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["last_pocar_opened_at"] == "2025-01-01"

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="monitoring_time_raw")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# PersonaTransformer Tests
# ---------------------------------------------------------------------------


class TestPersonaTransformer:
    """PersonaTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = PersonaTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "personaID": "patient-800",
            "provider_details": {"program_id": "RPM-001"},
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="persona")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "persona"
        assert result["patient_id"] == "patient-800"
        assert result["features"]["program_id"] == "RPM-001"

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="persona")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        """Uses personaID not persona_id — persona_id should NOT match."""
        change_doc = _make_change_doc("insert", full_document={"persona_id": "wrong-field"}, collection="persona")
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        change_doc = _make_change_doc("insert", full_document={"personaID": "p1"}, collection="persona")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["program_id"] is None

    def test_persona_id_field_is_personaID(self) -> None:
        """Verify the known pitfall: persona uses personaID, not persona_id."""
        doc = {"personaID": "correct", "persona_id": "wrong"}
        change_doc = _make_change_doc("insert", full_document=doc, collection="persona")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["patient_id"] == "correct"

    def test_camelcase_provider_details(self) -> None:
        """Supports camelCase providerDetails."""
        doc = {"personaID": "p1", "providerDetails": {"programId": "CCM-002"}}
        change_doc = _make_change_doc("insert", full_document=doc, collection="persona")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["program_id"] == "CCM-002"

    def test_provider_details_list(self) -> None:
        """provider_details as a list extracts first program_id."""
        doc = {
            "personaID": "p1",
            "provider_details": [
                {"program_id": "RPM-X"},
                {"program_id": "CCM-Y"},
            ],
        }
        change_doc = _make_change_doc("insert", full_document=doc, collection="persona")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["program_id"] == "RPM-X"

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="persona")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# DashboardDetailsTransformer Tests
# ---------------------------------------------------------------------------


class TestDashboardDetailsTransformer:
    """DashboardDetailsTransformer unit tests."""

    def setup_method(self) -> None:
        self.transformer = DashboardDetailsTransformer()

    def _full_doc(self, **overrides: object) -> dict:
        doc = {
            "persona_id": "patient-900",
            "billableMinutesMtd": 15,
        }
        doc.update(overrides)
        return doc

    def test_insert_operation(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="persona.dashboard_details")
        result = self.transformer.transform(change_doc)

        assert result is not None
        assert result["collection"] == "persona.dashboard_details"
        assert result["patient_id"] == "patient-900"
        assert result["features"]["billable_minutes_mtd"] == 15
        # 15 minutes → next threshold is 20 → 5 minutes remaining
        assert result["features"]["minutes_to_threshold"] == 5

    def test_delete_returns_none(self) -> None:
        change_doc = _make_change_doc("delete", include_full_doc=False, collection="persona.dashboard_details")
        assert self.transformer.transform(change_doc) is None

    def test_missing_patient_id_returns_none(self) -> None:
        change_doc = _make_change_doc(
            "insert", full_document={"billableMinutesMtd": 10}, collection="persona.dashboard_details"
        )
        assert self.transformer.transform(change_doc) is None

    def test_partial_features(self) -> None:
        change_doc = _make_change_doc(
            "insert", full_document={"persona_id": "p1"}, collection="persona.dashboard_details"
        )
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["billable_minutes_mtd"] is None
        assert result["features"]["minutes_to_threshold"] is None

    def test_threshold_tiers(self) -> None:
        """Test threshold computation for various billable minute values."""
        cases = [
            (0, 20),  # 0 → 20 minutes to threshold
            (10, 10),  # 10 → 10 minutes to next (20)
            (20, 20),  # 20 → 20 minutes to next (40)
            (35, 5),  # 35 → 5 minutes to next (40)
            (40, 20),  # 40 → 20 minutes to next (60)
            (55, 5),  # 55 → 5 minutes to next (60)
            (60, 0),  # 60 → past all thresholds
            (100, 0),  # 100 → past all thresholds
        ]
        for billable, expected in cases:
            doc = {"persona_id": "p1", "billableMinutesMtd": billable}
            change_doc = _make_change_doc("insert", full_document=doc, collection="persona.dashboard_details")
            result = self.transformer.transform(change_doc)
            assert result is not None, f"billable={billable}"
            assert result["features"]["minutes_to_threshold"] == expected, (
                f"billable={billable}: expected {expected}, got {result['features']['minutes_to_threshold']}"
            )

    def test_snake_case_billable_field(self) -> None:
        """Supports snake_case field name."""
        doc = {"persona_id": "p1", "billable_minutes_mtd": 25}
        change_doc = _make_change_doc("insert", full_document=doc, collection="persona.dashboard_details")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert result["features"]["billable_minutes_mtd"] == 25
        assert result["features"]["minutes_to_threshold"] == 15  # next threshold: 40

    def test_collection_name_has_dot(self) -> None:
        """Verify the collection name in output contains a dot."""
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="persona.dashboard_details")
        result = self.transformer.transform(change_doc)
        assert result is not None
        assert "." in result["collection"]

    def test_no_phi_in_output(self) -> None:
        change_doc = _make_change_doc("insert", full_document=self._full_doc(), collection="persona.dashboard_details")
        result = self.transformer.transform(change_doc)
        assert result is not None
        _assert_phi_guard(result)

    def test_conforms_to_protocol(self) -> None:
        assert isinstance(self.transformer, BaseTransformer)


# ---------------------------------------------------------------------------
# TRANSFORMER_REGISTRY Tests
# ---------------------------------------------------------------------------


class TestTransformerRegistry:
    """Tests for the TRANSFORMER_REGISTRY module-level dict."""

    def test_registry_has_9_entries(self) -> None:
        assert len(TRANSFORMER_REGISTRY) == 9

    def test_all_values_are_base_transformer(self) -> None:
        for name, transformer in TRANSFORMER_REGISTRY.items():
            assert isinstance(transformer, BaseTransformer), (
                f"Registry entry '{name}' is not a BaseTransformer: {type(transformer)}"
            )

    def test_expected_collection_names(self) -> None:
        expected = {
            "alerts",
            "chatRooms",
            "activity",
            "provider_protocols",
            "patient_care_plans",
            "patient_note",
            "monitoring_time_raw",
            "persona",
            "persona.dashboard_details",
        }
        assert set(TRANSFORMER_REGISTRY.keys()) == expected
