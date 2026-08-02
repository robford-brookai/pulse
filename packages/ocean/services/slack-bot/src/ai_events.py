"""AI audit event publisher for ocean.ai-ops topic.

All AI actions (summary generated, draft created, draft approved, draft rejected)
publish canonical events here. Audit failure must not break user flow.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import structlog

log = structlog.get_logger()


async def publish_ai_event(
    publisher,
    event_type: str,
    task_id: str,
    patient_id: str,
    payload: dict,
) -> None:
    """Publish a canonical AI audit event to ocean.ai-ops.

    PHI safety: patient_id is hashed with sha256 before inclusion — raw patient_id
    never reaches the event stream.

    On exception: logs error and returns without re-raising. Audit failure must
    not break the user-facing Slack interaction.
    """
    try:
        patient_id_hash = hashlib.sha256(patient_id.encode()).hexdigest()

        # Build canonical event envelope
        event_payload = {"patient_id_hash": patient_id_hash}
        event_payload.update(payload)

        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_system": "ocean",
            "entity_type": "task",
            "entity_id": task_id,
            "payload": event_payload,
        }

        await publisher.publish("ocean.ai-ops", event)

        log.info(
            "ai_event_published",
            event_type=event_type,
            task_id=task_id,
        )

    except Exception:
        log.error(
            "ai_event_publish_failed",
            event_type=event_type,
            task_id=task_id,
        )
        # Do NOT re-raise — audit failure must not break user flow
