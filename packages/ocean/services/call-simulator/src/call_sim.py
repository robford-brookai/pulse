"""Call lifecycle simulation logic.

Consumes outreach approval events and produces call.started, call.connected,
call.completed, and call.missed events on ocean.interactions.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from uuid import uuid4

import structlog

from src.publisher import RedpandaPublisher

log = structlog.get_logger()

TOPIC = "ocean.interactions"


def build_call_event(
    event_type: str,
    entity_id: str,
    correlation_id: str,
    payload: dict,
) -> dict:
    """Construct a BaseEvent-compatible dict for a call event."""
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_system": "call-simulator",
        "entity_type": "interaction",
        "entity_id": entity_id,
        "correlation_id": correlation_id,
        "actor_id": None,
        "payload": payload,
    }


async def simulate_call(approval_event: dict, publisher: RedpandaPublisher) -> None:
    """Run a full call lifecycle based on an outreach approval event.

    Extracts persona configuration from the approval payload and simulates
    a call attempt with optional retries for missed calls.
    """
    payload = approval_event["payload"]
    correlation_id = approval_event["correlation_id"]
    patient_id = payload["patient_id"]
    persona_id = payload["persona_id"]
    call_answer_rate = payload["call_answer_rate"]
    missed_call_retry_count = payload.get("missed_call_retry_count", 0)
    retry_delay_seconds = payload.get("retry_delay_seconds", 120)
    compression_ratio = payload.get("compression_ratio", 1)

    max_attempts = 1 + missed_call_retry_count

    for attempt in range(max_attempts):
        interaction_id = str(uuid4())
        base_payload = {"patient_id": patient_id, "persona_id": persona_id}

        # Publish call.started
        started = build_call_event(
            event_type="call.started",
            entity_id=interaction_id,
            correlation_id=correlation_id,
            payload={**base_payload, "attempt": attempt + 1},
        )
        await publisher.publish(TOPIC, started)
        log.info("call_started", interaction_id=interaction_id, attempt=attempt + 1)

        # Ring delay
        ring_delay = random.uniform(5, 15) / compression_ratio
        await asyncio.sleep(ring_delay)

        # Determine answer
        answered = random.random() < call_answer_rate

        if answered:
            # Publish call.connected
            connected = build_call_event(
                event_type="call.connected",
                entity_id=interaction_id,
                correlation_id=correlation_id,
                payload=base_payload,
            )
            await publisher.publish(TOPIC, connected)
            log.info("call_connected", interaction_id=interaction_id)

            # Talk delay
            talk_duration = random.uniform(60, 300)
            talk_delay = talk_duration / compression_ratio
            await asyncio.sleep(talk_delay)

            # Publish call.completed
            completed = build_call_event(
                event_type="call.completed",
                entity_id=interaction_id,
                correlation_id=correlation_id,
                payload={**base_payload, "duration_seconds": round(talk_duration, 1)},
            )
            await publisher.publish(TOPIC, completed)
            log.info("call_completed", interaction_id=interaction_id, duration=talk_duration)
            return  # Call succeeded, no more retries

        # Publish call.missed
        missed = build_call_event(
            event_type="call.missed",
            entity_id=interaction_id,
            correlation_id=correlation_id,
            payload={**base_payload, "attempt": attempt + 1},
        )
        await publisher.publish(TOPIC, missed)
        log.info("call_missed", interaction_id=interaction_id, attempt=attempt + 1)

        # Wait before retry (skip wait after last attempt)
        if attempt < max_attempts - 1:
            retry_wait = retry_delay_seconds / compression_ratio
            await asyncio.sleep(retry_wait)

    log.info(
        "call_all_attempts_exhausted",
        patient_id=patient_id,
        total_attempts=max_attempts,
    )
