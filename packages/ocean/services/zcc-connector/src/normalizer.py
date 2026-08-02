"""ZCC event normalizer — maps Zoom Contact Center events to Ocean canonical event envelope.

NOTE: Event name mapping has MEDIUM confidence — based on ZCC API research.
Log all received event names at INFO level (in receiver.py) so actual names can be
confirmed against a real ZCC account (Pitfall 1 mitigation from RESEARCH.md).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

log = structlog.get_logger()

# MEDIUM confidence: event names derived from ZCC API documentation research.
# Log raw event name before normalization to confirm actual names in production.
ZCC_TO_OCEAN_EVENT_TYPE: dict[str, str] = {
    "contact_center.engagement_started": "call.started",
    "contact_center.engagement_answered": "call.connected",
    "contact_center.engagement_ended": "call.completed",
    "contact_center.engagement_missed": "call.missed",
}


def normalize_zcc_event(raw: dict) -> dict | None:
    """Map a ZCC webhook payload to a canonical Ocean event envelope.

    Returns None for unmapped (unknown) ZCC event types.

    The caller (receiver.py) logs the raw event name at INFO level BEFORE calling
    this function, so unknown events are always traceable.
    """
    zcc_event = raw.get("event", "")
    ocean_event_type = ZCC_TO_OCEAN_EVENT_TYPE.get(zcc_event)
    if ocean_event_type is None:
        return None

    obj = raw.get("payload", {}).get("object", {})
    engagement_id = obj.get("engagement_id") or obj.get("id", "")
    agent_id = obj.get("assigned_to", {}).get("id", "")
    duration_seconds = obj.get("duration", 0)
    disposition = obj.get("disposition_name", "")
    patient_id = obj.get("patient_id", "")
    task_id = obj.get("task_id", "")

    return {
        "event_id": str(uuid.uuid4()),
        "event_type": ocean_event_type,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "source_system": "zcc",
        "entity_type": "interaction",
        "entity_id": engagement_id,
        "actor_id": agent_id,
        "payload": {
            "engagement_id": engagement_id,
            "agent_id": agent_id,
            "duration_seconds": duration_seconds,
            "disposition": disposition,
            "patient_id": patient_id,
            "task_id": task_id,
        },
    }
