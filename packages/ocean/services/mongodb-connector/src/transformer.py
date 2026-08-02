"""BaseTransformer protocol and collection-specific transformers for MongoDB CDC events."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class BaseTransformer(Protocol):
    """Protocol for transforming raw MongoDB change events into payload dicts.

    Implementations return a dict with ``collection``, ``patient_id``,
    ``operation_type``, and ``features`` keys — or ``None`` to signal
    the event should be skipped (e.g. delete operations).
    """

    def transform(self, change_doc: dict) -> dict | None: ...


class AlertsTransformer:
    """Transform MongoDB ``alerts`` collection change events.

    Ports care-nexus ``alerts.go`` logic: extracts ``patientId``,
    ``status``, ``type``, ``clearedAt``, and ``vitalType`` from the
    ``fullDocument`` and maps them to feature column names.
    """

    def transform(self, change_doc: dict) -> dict | None:
        operation_type = change_doc.get("operationType", "")

        # Delete events carry no fullDocument — nothing to transform.
        if operation_type == "delete":
            return None

        full_doc = change_doc.get("fullDocument")
        if full_doc is None:
            return None

        patient_id = full_doc.get("patientId")
        if patient_id is None:
            logger.warning(
                "missing_patient_id",
                collection="alerts",
                operation_type=operation_type,
                document_key=change_doc.get("documentKey"),
            )
            return None

        return {
            "collection": "alerts",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "alert_status": full_doc.get("status"),
                "alert_type": full_doc.get("type"),
                "cleared_at": (str(full_doc["clearedAt"]) if full_doc.get("clearedAt") else None),
                "vital_type": full_doc.get("vitalType"),
            },
        }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str | None:
    """Convert a value to string if non-None, else return None."""
    return str(value) if value is not None else None


def _extract_common(
    change_doc: dict,
    collection: str,
    patient_id_field: str,
) -> tuple[str, dict, str | None] | None:
    """Shared preamble for all transformers.

    Returns ``(operation_type, full_doc, patient_id)`` or ``None`` if the
    event should be skipped (delete / missing fullDocument / missing patient_id).
    """
    operation_type = change_doc.get("operationType", "")

    if operation_type == "delete":
        return None

    full_doc = change_doc.get("fullDocument")
    if full_doc is None:
        return None

    patient_id = full_doc.get(patient_id_field)
    if patient_id is None:
        logger.warning(
            "missing_patient_id",
            collection=collection,
            operation_type=operation_type,
            document_key=change_doc.get("documentKey"),
        )
        return None

    return operation_type, full_doc, patient_id


# ---------------------------------------------------------------------------
# ChatRoomsTransformer
# ---------------------------------------------------------------------------


class ChatRoomsTransformer:
    """Transform ``chatRooms`` collection change events.

    Only processes rooms of type ``expert`` (case-insensitive).
    Patient ID is extracted from the first subscriber with a ``personaID``.
    """

    def transform(self, change_doc: dict) -> dict | None:
        operation_type = change_doc.get("operationType", "")
        if operation_type == "delete":
            return None

        full_doc = change_doc.get("fullDocument")
        if full_doc is None:
            return None

        # Filter: only expert chat rooms
        room_type = full_doc.get("type", "")
        if not isinstance(room_type, str) or room_type.lower() != "expert":
            return None

        # Extract patient_id from first subscriber with personaID
        patient_id: str | None = None
        for subscriber in full_doc.get("subscribers", []):
            if isinstance(subscriber, dict):
                pid = subscriber.get("personaID")
                if pid is not None:
                    patient_id = pid
                    break

        if patient_id is None:
            logger.warning(
                "missing_patient_id",
                collection="chatRooms",
                operation_type=operation_type,
                document_key=change_doc.get("documentKey"),
            )
            return None

        return {
            "collection": "chatRooms",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "unread_message_count": full_doc.get("unread_message_count"),
                "latest_message_timestamp": _stringify(full_doc.get("latest_message_timestamp")),
            },
        }


# ---------------------------------------------------------------------------
# ActivityTransformer
# ---------------------------------------------------------------------------


class ActivityTransformer:
    """Transform ``activity`` collection change events."""

    def transform(self, change_doc: dict) -> dict | None:
        result = _extract_common(change_doc, "activity", "persona_id")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        # Try camelCase then snake_case for lastReadingAt
        last_reading_at = full_doc.get("lastReadingAt") or full_doc.get("last_reading_at")

        return {
            "collection": "activity",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "last_reading_at": _stringify(last_reading_at),
                "readings_count_current": 1,
            },
        }


# ---------------------------------------------------------------------------
# ProviderProtocolsTransformer
# ---------------------------------------------------------------------------


class ProviderProtocolsTransformer:
    """Transform ``provider_protocols`` collection change events."""

    def transform(self, change_doc: dict) -> dict | None:
        result = _extract_common(change_doc, "provider_protocols", "persona_id")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        adherence = full_doc.get("adherenceRate")
        if adherence is not None:
            try:
                adherence = float(adherence)
            except (TypeError, ValueError):
                adherence = None

        return {
            "collection": "provider_protocols",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "protocol_adherence_rate": adherence,
                "missed_readings_period": full_doc.get("missedReadingsPeriod"),
            },
        }


# ---------------------------------------------------------------------------
# PatientCarePlansTransformer
# ---------------------------------------------------------------------------

_CARE_PLAN_SECTIONS: tuple[str, ...] = (
    "problem_list",
    "current_medications",
    "allergies",
    "preventative_care",
    "psychosocial_assessment",
    "care_teams",
)


class PatientCarePlansTransformer:
    """Transform ``patient_care_plans`` collection change events.

    Traverses 6 named sections and ``condition_specific_care_plans`` to
    compute ``care_plan_count`` and ``care_plan_last_updated``.
    """

    def transform(self, change_doc: dict) -> dict | None:
        result = _extract_common(change_doc, "patient_care_plans", "persona_id")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        care_plan_count = 0
        latest_ts: str | None = None

        for section_name in _CARE_PLAN_SECTIONS:
            section = full_doc.get(section_name)
            if section:
                care_plan_count += 1
                latest_ts = _pick_latest(
                    latest_ts,
                    section.get("updated_at") if isinstance(section, dict) else None,
                    section.get("reviewed_at") if isinstance(section, dict) else None,
                )

        # Traverse condition_specific_care_plans entries
        for entry in full_doc.get("condition_specific_care_plans", []):
            if isinstance(entry, dict):
                latest_ts = _pick_latest(
                    latest_ts,
                    entry.get("updated_at"),
                    entry.get("reviewed_at"),
                )

        return {
            "collection": "patient_care_plans",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "care_plan_count": care_plan_count,
                "care_plan_last_updated": _stringify(latest_ts),
                "ccm_chart_reviewed_at": _stringify(full_doc.get("ccmChartReviewedAt")),
                "follow_up_due_today_or_overdue": full_doc.get("followUpDueTodayOrOverdue"),
            },
        }


def _pick_latest(*values: Any) -> str | None:
    """Return the lexicographically latest non-None stringified value."""
    candidates = [str(v) for v in values if v is not None]
    return max(candidates) if candidates else None


# ---------------------------------------------------------------------------
# PatientNoteTransformer
# ---------------------------------------------------------------------------


class PatientNoteTransformer:
    """Transform ``patient_note`` collection change events.

    Only emits events for interaction notes (determined by presence of
    ``is_interaction`` or ``interaction`` fields).
    """

    def transform(self, change_doc: dict) -> dict | None:
        result = _extract_common(change_doc, "patient_note", "persona_id")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        # Only emit for interaction notes
        is_interaction = full_doc.get("is_interaction") or full_doc.get("interaction")
        if not is_interaction:
            return None

        return {
            "collection": "patient_note",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "pending_emr_notes": full_doc.get("pendingEmrNotes"),
                "last_nurse_interaction_at": _stringify(full_doc.get("last_nurse_interaction_at")),
                "last_contact_at": _stringify(full_doc.get("last_contact_at")),
            },
        }


# ---------------------------------------------------------------------------
# MonitoringTimeRawTransformer
# ---------------------------------------------------------------------------

_TIMESTAMP_CANDIDATES: tuple[str, ...] = (
    "lastPocarOpenedAt",
    "last_pocar_opened_at",
    "pocarOpenedAt",
    "pocar_opened_at",
    "openedAt",
    "opened_at",
    "lastOpenedAt",
    "last_opened_at",
    "updatedAt",
    "updated_at",
    "createdAt",
    "created_at",
)


class MonitoringTimeRawTransformer:
    """Transform ``monitoring_time_raw`` collection change events.

    Tries multiple timestamp field candidates in priority order for
    ``last_pocar_opened_at``.
    """

    def transform(self, change_doc: dict) -> dict | None:
        result = _extract_common(change_doc, "monitoring_time_raw", "persona_id")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        ts_value: Any = None
        for candidate in _TIMESTAMP_CANDIDATES:
            ts_value = full_doc.get(candidate)
            if ts_value is not None:
                break

        return {
            "collection": "monitoring_time_raw",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "last_pocar_opened_at": _stringify(ts_value),
            },
        }


# ---------------------------------------------------------------------------
# PersonaTransformer
# ---------------------------------------------------------------------------


class PersonaTransformer:
    """Transform ``persona`` collection change events.

    **Important:** Uses ``personaID`` (not ``persona_id``) for patient_id
    extraction — this is a known field-naming pitfall in the persona collection.
    """

    def transform(self, change_doc: dict) -> dict | None:
        # persona uses personaID — not persona_id
        result = _extract_common(change_doc, "persona", "personaID")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        # Derive program_id from provider_details or providerDetails
        provider_details = full_doc.get("provider_details") or full_doc.get("providerDetails")
        program_id: str | None = None
        if isinstance(provider_details, dict):
            program_id = provider_details.get("program_id") or provider_details.get("programId")
        elif isinstance(provider_details, list):
            # Take first program identifier found
            for pd in provider_details:
                if isinstance(pd, dict):
                    pid = pd.get("program_id") or pd.get("programId")
                    if pid is not None:
                        program_id = pid
                        break

        return {
            "collection": "persona",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "program_id": program_id,
            },
        }


# ---------------------------------------------------------------------------
# DashboardDetailsTransformer
# ---------------------------------------------------------------------------

_BILLING_THRESHOLDS: tuple[int, ...] = (20, 40, 60)


class DashboardDetailsTransformer:
    """Transform ``persona.dashboard_details`` collection change events.

    Computes ``minutes_to_threshold`` — minutes remaining to the next
    billing tier (20, 40, 60).
    """

    def transform(self, change_doc: dict) -> dict | None:
        result = _extract_common(change_doc, "persona.dashboard_details", "persona_id")
        if result is None:
            return None
        operation_type, full_doc, patient_id = result

        billable = full_doc.get("billableMinutesMtd")
        if billable is None:
            billable = full_doc.get("billable_minutes_mtd")

        minutes_to_threshold: int | None = None
        if billable is not None:
            try:
                billable_num = float(billable)
                for threshold in _BILLING_THRESHOLDS:
                    if billable_num < threshold:
                        minutes_to_threshold = int(threshold - billable_num)
                        break
                else:
                    # Already past all thresholds
                    minutes_to_threshold = 0
            except (TypeError, ValueError):
                pass

        return {
            "collection": "persona.dashboard_details",
            "patient_id": patient_id,
            "operation_type": operation_type,
            "features": {
                "billable_minutes_mtd": billable,
                "minutes_to_threshold": minutes_to_threshold,
            },
        }


# ---------------------------------------------------------------------------
# Transformer Registry
# ---------------------------------------------------------------------------

TRANSFORMER_REGISTRY: dict[str, BaseTransformer] = {
    "alerts": AlertsTransformer(),
    "chatRooms": ChatRoomsTransformer(),
    "activity": ActivityTransformer(),
    "provider_protocols": ProviderProtocolsTransformer(),
    "patient_care_plans": PatientCarePlansTransformer(),
    "patient_note": PatientNoteTransformer(),
    "monitoring_time_raw": MonitoringTimeRawTransformer(),
    "persona": PersonaTransformer(),
    "persona.dashboard_details": DashboardDetailsTransformer(),
}
