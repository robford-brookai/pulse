"""SQS consumer for agent-worker.

Receives EventBridge-delivered events from the agent-worker queue, filters for
task.created from control-plane only, dispatches to claim competition, then runs
the AI decision pipeline.

Ordering verdict: order-tolerant. The consumer handles a single event type
(task.created) from a single source (control-plane); there is no cross-event
lifecycle, so delivery order cannot change the final state.

Receive → process → delete: a message is deleted only after handle_message
returns, so a failure is left to visibility-timeout redelivery. This preserves
the at-least-once, commit-after-success semantics the Kafka consumer had.
Blocking boto3 calls are offloaded to a thread via asyncio.to_thread() so the
event loop is never blocked and the FastAPI /health endpoint stays responsive.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import structlog
from ocean_broker import EventBridgePublisher

from src.claim import compete_for_claim
from src.decision import decide_with_fallback
from src.events import publish_ai_decision, publish_ai_recommendation, publish_task_completed
from src.personas import Persona

log = structlog.get_logger()

SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME_SECONDS = 20
SQS_ERROR_BACKOFF_SECONDS = 5


async def handle_message(
    event_data: dict,
    personas: list[Persona],
    publisher: EventBridgePublisher,
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
    log.info(f"[AI] Patient {alert_context['patient_id']}: {action} (confidence={confidence:.2f}) by {persona.id}")

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


def _envelope_from_body(body: object) -> dict | None:
    """Extract the event envelope from a parsed SQS message body.

    An EventBridge rule delivers the envelope whole inside ``detail``. A body
    with no ``detail`` key is accepted as a bare envelope so local tooling can
    send straight to the queue.
    """
    if not isinstance(body, dict):
        return None
    detail = body.get("detail", body)
    return detail if isinstance(detail, dict) else None


async def run_consumer(
    personas: list[Persona],
    queue_url: str,
    publisher: EventBridgePublisher,
    claimed_tasks: set[str],
    *,
    sqs_client: Any = None,
) -> None:
    """Run the agent-worker consumer loop against its SQS queue.

    Deletes a message only after successful processing; a failed or malformed
    message is left for visibility-timeout redelivery (the queue's redrive
    policy dead-letters a poison message). Blocking receive/delete calls run
    in a thread so the asyncio event loop stays free for /health.
    """
    if sqs_client is None:
        import boto3

        sqs_client = boto3.client("sqs")

    log.info("agent_worker_consumer_started", queue_url=queue_url)

    while True:
        try:
            response = await asyncio.to_thread(
                sqs_client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=SQS_MAX_MESSAGES,
                WaitTimeSeconds=SQS_WAIT_TIME_SECONDS,
            )
        except Exception:
            log.exception("sqs_receive_failed", queue_url=queue_url)
            await asyncio.sleep(SQS_ERROR_BACKOFF_SECONDS)
            continue

        for msg in response.get("Messages", []):
            receipt_handle = msg.get("ReceiptHandle", "")

            try:
                body = json.loads(msg["Body"])
            except (json.JSONDecodeError, KeyError):
                log.warning("sqs_malformed_message", receipt_handle=receipt_handle)
                continue

            event_data = _envelope_from_body(body)
            if event_data is None:
                log.warning("sqs_body_not_an_envelope", receipt_handle=receipt_handle)
                continue

            try:
                await handle_message(event_data, personas, publisher, claimed_tasks)
            except Exception:
                log.exception("agent_worker_dispatch_failed", receipt_handle=receipt_handle)
                continue

            try:
                await asyncio.to_thread(
                    sqs_client.delete_message,
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle,
                )
            except Exception:
                log.exception("sqs_delete_failed", receipt_handle=receipt_handle)
