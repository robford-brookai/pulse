"""BaseTransformer protocol and AlertsTransformer for MongoDB CDC events."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

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
                "cleared_at": (
                    str(full_doc["clearedAt"]) if full_doc.get("clearedAt") else None
                ),
                "vital_type": full_doc.get("vitalType"),
            },
        }
