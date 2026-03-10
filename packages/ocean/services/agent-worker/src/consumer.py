"""Async Kafka consumer for agent-worker.

Reads from ocean.tasks, filters for task.created from control-plane only,
dispatches to claim competition, then runs AI decision pipeline.
"""
from __future__ import annotations

import json
import random

import structlog
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer

from src.claim import compete_for_claim
from src.decision import decide_with_fallback
from src.events import publish_ai_decision, publish_ai_recommendation, publish_task_completed
from src.personas import Persona
from src.publisher import RedpandaPublisher

log = structlog.get_logger()

TOPICS = ["ocean.tasks"]

CONSUMER_CONFIG: dict = {
    "group.id": "agent-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
}


async def handle_message(
    event_data: dict,
    personas: list[Persona],
    publisher: RedpandaPublisher,
    claimed_tasks: set[str],
) -> str:
    """Process a single deserialized event. Returns status string for testing."""
    source = event_data.get("source_system", "")
    if source != "control-plane":
        log.debug("skipped_source_system", source_system=source)
        return "skipped_source"

    event_type = event_data.get("event_type", "")
    if event_type != "task.created":
        log.debug("skipped_event_type", event_type=event_type)
        return "skipped_type"

    persona = await compete_for_claim(event_data, personas, publisher, claimed_tasks)
    if persona is None:
        return "dispatched"

    # Build alert context from task event payload
    payload = event_data.get("payload", {})
    raw_signal = payload.get("signal_type", payload.get("task_type", ""))
    alert_context = {
        "priority": payload.get("priority", ""),
        "signal_type": raw_signal.removesuffix("_anomaly"),
        "severity": payload.get("severity", payload.get("priority", "")).upper(),
        "patient_id": payload.get("patient_id", event_data.get("entity_id", "")),
        "value": payload.get("value"),
        "anomalous": payload.get("anomalous"),
    }

    # AI decision pipeline (falls back to deterministic rules)
    action, confidence = await decide_with_fallback(alert_context)
    log.info(
        f"[AI] Patient {alert_context['patient_id']}: {action}"
        f" (confidence={confidence:.2f}) by {persona.id}"
    )

    # Publish recommendation
    await publish_ai_recommendation(publisher, event_data, action, confidence, persona)

    # Persona approve-rate gate (post-LLM)
    approve_rate = persona.outreach_approve_rate or 0.5
    approved = action == "approve" and random.random() < approve_rate
    log.info(
        f"[GATE] Patient {alert_context['patient_id']}:"
        f" outreach {'APPROVED' if approved else 'REJECTED'} by {persona.id}"
    )

    # Publish approved/rejected decision
    await publish_ai_decision(publisher, event_data, action, confidence, persona, approved, alert_context)

    # Complete the task
    await publish_task_completed(publisher, event_data, persona)

    log.info(
        "decision_cycle_complete",
        persona=persona.id,
        action=action,
        confidence=confidence,
        approved=approved,
        entity_id=event_data.get("entity_id", ""),
    )
    return "dispatched"


async def run_consumer(
    personas: list[Persona],
    bootstrap_servers: str,
    publisher: RedpandaPublisher,
    claimed_tasks: set[str],
) -> None:
    """Run the agent-worker consumer loop."""
    conf = {**CONSUMER_CONFIG, "bootstrap.servers": bootstrap_servers}
    consumer = Consumer(conf)
    await consumer.subscribe(TOPICS)
    log.info("agent_worker_consumer_started", topics=TOPICS, brokers=bootstrap_servers)

    try:
        while True:
            msg = await consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("consumer_error", error=str(msg.error()))
                continue

            try:
                event_data = json.loads(msg.value())
                await handle_message(event_data, personas, publisher, claimed_tasks)
                await consumer.commit(message=msg)
            except Exception:
                log.exception(
                    "agent_worker_dispatch_failed",
                    offset=msg.offset(),
                    topic=msg.topic(),
                )
    finally:
        await consumer.close()
        log.info("agent_worker_consumer_closed")
