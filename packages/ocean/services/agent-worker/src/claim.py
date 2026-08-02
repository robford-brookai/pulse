"""Claim competition logic with persona delays."""

from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import UTC, datetime

import structlog
from ocean_broker import EventBridgePublisher

from src.personas import Persona

log = structlog.get_logger()


async def compete_for_claim(
    task_event: dict,
    personas: list[Persona],
    publisher: EventBridgePublisher,
    claimed_tasks: set[str],
    compression_ratio: float = 960,
) -> Persona | None:
    """Run claim competition among eligible personas.

    Excludes human_escalation_responder personas. Sorts remaining by
    random delay within each persona's claim_delay_seconds range.
    First persona whose entity_id is not already claimed wins.
    """
    entity_id = task_event.get("entity_id", "")

    # Already claimed -- skip
    if entity_id in claimed_tasks:
        log.info("claim_duplicate_skipped", entity_id=entity_id)
        return None

    # Filter out escalation responders
    eligible = [p for p in personas if not p.human_escalation_responder]
    if not eligible:
        log.info("claim_no_eligible_personas")
        return None

    # Sort by random delay within each persona's range
    def _random_delay(p: Persona) -> float:
        if p.claim_delay_seconds is None:
            return 0.0
        lo, hi = p.claim_delay_seconds
        return random.uniform(lo, hi)

    candidates = sorted(eligible, key=_random_delay)

    for persona in candidates:
        delay = _random_delay(persona)
        compressed = delay / compression_ratio
        await asyncio.sleep(compressed)

        # Check again after delay (another persona may have claimed)
        if entity_id in claimed_tasks:
            log.info("claim_lost_race", persona=persona.id, entity_id=entity_id)
            return None

        # Claim it
        claimed_tasks.add(entity_id)
        patient_id = task_event.get("payload", {}).get("patient_id", "unknown")
        log.info(f"[CLAIM] {persona.id} claimed task for patient {patient_id}")

        # Build task.claimed event with BaseEvent envelope
        correlation_id = task_event.get("correlation_id", "")
        event_id = hashlib.sha256(f"task.claimed:{entity_id}:{persona.id}".encode()).hexdigest()

        claimed_event = {
            "event_id": event_id,
            "event_type": "task.claimed",
            "schema_version": "1.0.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "source_system": "agent-worker",
            "entity_type": "task",
            "entity_id": entity_id,
            "correlation_id": correlation_id,
            "actor_id": persona.id,
            "payload": {
                "persona_id": persona.id,
                "persona_role": persona.role,
            },
        }

        await publisher.publish("tasks", claimed_event)
        log.info(
            "task_claimed",
            persona=persona.id,
            entity_id=entity_id,
            correlation_id=correlation_id,
        )
        return persona

    return None
