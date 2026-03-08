"""Event builders for agent-worker events.

All publish functions are fire-and-forget: log errors but never re-raise.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import structlog

from src.personas import Persona
from src.publisher import RedpandaPublisher

log = structlog.get_logger()


def build_agent_event(
    event_type: str,
    entity_id: str,
    entity_type: str,
    correlation_id: str,
    payload: dict,
) -> dict:
    """Build a BaseEvent envelope with source_system='agent-worker'."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_system": "agent-worker",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "correlation_id": correlation_id,
        "actor_id": None,
        "payload": payload,
    }


async def publish_ai_recommendation(
    publisher: RedpandaPublisher,
    task_data: dict,
    action: str,
    confidence: float,
    persona: Persona,
) -> None:
    """Publish ai.recommendation.generated to ocean.ai-ops."""
    try:
        event = build_agent_event(
            event_type="ai.recommendation.generated",
            entity_id=task_data.get("entity_id", ""),
            entity_type="task",
            correlation_id=task_data.get("correlation_id", ""),
            payload={
                "action": action,
                "confidence": confidence,
                "persona_id": persona.id,
                "persona_role": persona.role,
            },
        )
        await publisher.publish("ocean.ai-ops", event)
        log.info("ai_recommendation_published", entity_id=event["entity_id"])
    except Exception:
        log.exception("publish_ai_recommendation_failed")


async def publish_ai_decision(
    publisher: RedpandaPublisher,
    task_data: dict,
    action: str,
    confidence: float,
    persona: Persona,
    approved: bool,
    alert_context: dict | None = None,
) -> None:
    """Publish ai.output.approved or ai.output.rejected to ocean.ai-ops.

    For approved events, includes persona call config for call-simulator consumption.
    """
    try:
        event_type = "ai.output.approved" if approved else "ai.output.rejected"
        payload: dict = {
            "action": action,
            "confidence": confidence,
            "persona_id": persona.id,
            "persona_role": persona.role,
            "approved": approved,
        }

        if approved:
            compression_ratio = float(os.environ.get("COMPRESSION_RATIO", "960"))
            payload["call_answer_rate"] = persona.call_answer_rate
            payload["missed_call_retry_count"] = persona.missed_call_retry_count
            payload["retry_delay_seconds"] = persona.retry_delay_seconds
            payload["compression_ratio"] = compression_ratio
            if alert_context:
                payload["patient_id"] = alert_context.get("patient_id", "")
                payload["severity"] = alert_context.get("severity", "")
                payload["signal_type"] = alert_context.get("signal_type", "")

        event = build_agent_event(
            event_type=event_type,
            entity_id=task_data.get("entity_id", ""),
            entity_type="task",
            correlation_id=task_data.get("correlation_id", ""),
            payload=payload,
        )
        await publisher.publish("ocean.ai-ops", event)
        log.info("ai_decision_published", event_type=event_type, entity_id=event["entity_id"])
    except Exception:
        log.exception("publish_ai_decision_failed")


async def publish_task_completed(
    publisher: RedpandaPublisher,
    task_data: dict,
    persona: Persona,
) -> None:
    """Publish task.completed to ocean.tasks."""
    try:
        event = build_agent_event(
            event_type="task.completed",
            entity_id=task_data.get("entity_id", ""),
            entity_type="task",
            correlation_id=task_data.get("correlation_id", ""),
            payload={
                "persona_id": persona.id,
                "persona_role": persona.role,
            },
        )
        await publisher.publish("ocean.tasks", event)
        log.info("task_completed_published", entity_id=event["entity_id"])
    except Exception:
        log.exception("publish_task_completed_failed")
