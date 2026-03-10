"""Async Kafka consumer for slack-bot.

Reads from ocean.tasks, ocean.ai-ops, ocean.interactions, ocean.ops;
dispatches events to handlers for alert cards, lifecycle thread updates,
and simulation bookends.

Consumer group: slack-bot-worker (receives events independently of other consumers).
Manual offset commit — offset committed only AFTER successful handler return.
"""

from __future__ import annotations

import hashlib
import json
import os
from uuid import uuid4

import sqlalchemy as sa
import structlog
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer

from src.ai_events import publish_ai_event
from src.ai_summary import generate_summary_with_context
from src.cards import (
    alert_card,
    outreach_draft_card,
    scenario_completed_card,
    scenario_started_card,
)

log = structlog.get_logger()

TOPICS = ["ocean.tasks", "ocean.ai-ops", "ocean.interactions", "ocean.ops"]

CONSUMER_CONFIG: dict = {
    "group.id": "slack-bot-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
}

# Priority-based channel routing for alert cards
CHANNEL_MAP: dict[str, str] = {
    "CRITICAL": "#ocean-critical",
    "URGENT": "#ocean-urgent",
    "ROUTINE": "#ocean-routine",
}
DEFAULT_CHANNEL = "#ocean-alerts"


async def handle_task_created(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle task.created event: generate AI summary, build card, post to Slack.

    Phase 4 upgrade:
    - Calls generate_summary_with_context with Hasura graph context
    - Posts outreach draft card with Approve/Reject gate
    - Publishes ai.summary.generated and ai.response.drafted events

    Phase 15 upgrade:
    - Priority-based channel routing via CHANNEL_MAP
    - Stores parent message_ts via thread_manager
    """
    payload = event_data.get("payload", {})

    task_id = payload.get("task_id") or event_data.get("entity_id")
    patient_hash = payload.get("patient_id", "unknown")
    alert_type = payload.get("task_type", "unknown")
    severity = payload.get("priority", "routine").upper()
    timestamp = event_data.get("timestamp", "")
    alert_id = payload.get("alert_id", "")

    # Priority-based channel routing (Phase 15)
    channel = CHANNEL_MAP.get(severity, DEFAULT_CHANNEL)

    hasura_secret = os.environ.get("HASURA_GRAPHQL_ADMIN_SECRET", "")

    ai_summary, cited_signals = await generate_summary_with_context(
        alert_type=alert_type,
        severity=severity,
        patient_hash=patient_hash,
        timestamp=timestamp,
        hasura_url=hasura_url,
        hasura_secret=hasura_secret,
    )

    blocks = alert_card(
        task_id,
        patient_hash,
        alert_type,
        severity,
        timestamp,
        ai_summary,
        hasura_url,
        cited_signals=cited_signals,
    )

    response = await slack_client.chat_postMessage(
        channel=channel,
        blocks=blocks,
        text=f"[{severity}] {alert_type} alert",
    )

    # Store parent message for thread tracking (Phase 15)
    message_ts = (
        response.get("ts", "") if isinstance(response, dict) else getattr(response, "ts", "")
    )
    if thread_manager and message_ts:
        await thread_manager.store_parent_message(task_id, channel, message_ts)

    log.info(
        "alert_card_posted",
        task_id=task_id,
        channel=channel,
        alert_type=alert_type,
    )

    # Publish ai.summary.generated event
    output_hash = hashlib.sha256(ai_summary.encode()).hexdigest()
    if publisher is not None:
        await publish_ai_event(
            publisher=publisher,
            event_type="ai.summary.generated",
            task_id=task_id,
            patient_id=patient_hash,
            payload={
                "context_event_ids": [],
                "output_hash": output_hash,
            },
        )

    # Create and post outreach draft
    draft_id = str(uuid4())
    draft_text = f"Patient {patient_hash} has a {severity} {alert_type} alert. Please follow up."

    if session_maker is not None:
        async with session_maker() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO ai_drafts "
                    "(draft_id, task_id, patient_id, alert_id, draft_text, status) "
                    "VALUES (:draft_id, :task_id, :patient_id, :alert_id, :draft_text, 'pending')"
                ),
                {
                    "draft_id": draft_id,
                    "task_id": task_id,
                    "patient_id": patient_hash,
                    "alert_id": alert_id,
                    "draft_text": draft_text,
                },
            )
            await session.commit()

    draft_output_hash = hashlib.sha256(draft_text.encode()).hexdigest()
    if publisher is not None:
        await publish_ai_event(
            publisher=publisher,
            event_type="ai.response.drafted",
            task_id=task_id,
            patient_id=patient_hash,
            payload={
                "draft_id": draft_id,
                "output_hash": draft_output_hash,
            },
        )

    draft_blocks = outreach_draft_card(task_id, draft_id, draft_text)
    await slack_client.chat_postMessage(
        channel=channel,
        blocks=draft_blocks,
        text="AI Outreach Draft — review before dispatch",
    )

    log.info("outreach_draft_posted", task_id=task_id, draft_id=draft_id)


# ---------------------------------------------------------------------------
# Lifecycle stub handlers — queue updates through ThreadManager
# ---------------------------------------------------------------------------


async def _extract_task_id(event_data: dict) -> str:
    """Extract task_id from event payload or entity_id."""
    payload = event_data.get("payload", {})
    return payload.get("task_id") or event_data.get("entity_id", "unknown")


async def handle_task_claimed(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle task.claimed: extract actor, queue thread update, update parent status."""
    task_id = await _extract_task_id(event_data)
    payload = event_data.get("payload", {})
    actor = payload.get("persona_name") or payload.get("actor", "unknown")
    if thread_manager:
        await thread_manager.queue_update(task_id, {"type": "claimed", "actor": actor})
        await thread_manager.update_parent_status(task_id, "CLAIMED")
    log.info("task_claimed_handled", task_id=task_id, actor=actor)


async def handle_task_completed(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle task.completed: queue thread update, update parent to RESOLVED."""
    task_id = await _extract_task_id(event_data)
    if thread_manager:
        await thread_manager.queue_update(task_id, {"type": "task_completed"})
        await thread_manager.update_parent_status(task_id, "RESOLVED")
    log.info("task_completed_handled", task_id=task_id)


async def handle_ai_recommendation(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle ai.recommendation.generated: extract action, confidence, reasoning."""
    task_id = await _extract_task_id(event_data)
    payload = event_data.get("payload", {})
    if thread_manager:
        await thread_manager.queue_update(
            task_id,
            {
                "type": "ai_recommendation",
                "action": payload.get("action", ""),
                "confidence": payload.get("confidence", ""),
                "reasoning": payload.get("reasoning", ""),
            },
        )
    log.info("ai_recommendation_handled", task_id=task_id)


async def handle_ai_approved(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle ai.output.approved: extract actor."""
    task_id = await _extract_task_id(event_data)
    payload = event_data.get("payload", {})
    actor = payload.get("actor", "unknown")
    if thread_manager:
        await thread_manager.queue_update(task_id, {"type": "ai_approved", "actor": actor})
    log.info("ai_approved_handled", task_id=task_id)


async def handle_ai_rejected(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle ai.output.rejected: extract actor and reason."""
    task_id = await _extract_task_id(event_data)
    payload = event_data.get("payload", {})
    actor = payload.get("actor", "unknown")
    reason = payload.get("reason", "")
    if thread_manager:
        await thread_manager.queue_update(
            task_id, {"type": "ai_rejected", "actor": actor, "reason": reason}
        )
    log.info("ai_rejected_handled", task_id=task_id)


async def handle_call_event(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle call events (connected, missed, completed): extract outcome and duration."""
    task_id = await _extract_task_id(event_data)
    payload = event_data.get("payload", {})
    event_type = event_data.get("event_type", "call.unknown")
    outcome = payload.get("outcome") or event_type.split(".")[-1]
    duration = payload.get("duration_seconds")
    if thread_manager:
        update = {"type": "call_outcome", "outcome": outcome}
        if duration is not None:
            update["duration_seconds"] = duration
        await thread_manager.queue_update(task_id, update)
    log.info("call_event_handled", task_id=task_id, event_type=event_type, outcome=outcome)


async def handle_scenario_started(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle scenario.started: post header card directly to #ocean-alerts."""
    payload = event_data.get("payload", {})
    scenario_name = payload.get("scenario_name", "unknown")
    patients = payload.get("patients", [])
    flow_combos = payload.get("flow_combos", [])
    blocks = scenario_started_card(scenario_name, patients, flow_combos)
    try:
        await slack_client.chat_postMessage(
            channel=DEFAULT_CHANNEL,
            blocks=blocks,
            text=f"[SIMULATION] {scenario_name} started",
        )
    except Exception:
        log.warning("scenario_started_card_post_failed", scenario_name=scenario_name, exc_info=True)
    log.info("scenario_started_posted", scenario_name=scenario_name)


async def handle_scenario_completed(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Handle scenario.completed: post footer card with stats to #ocean-alerts."""
    payload = event_data.get("payload", {})
    scenario_name = payload.get("scenario_name", "unknown")
    stats = {k: v for k, v in payload.items() if k != "scenario_name"}
    blocks = scenario_completed_card(scenario_name, stats)
    try:
        await slack_client.chat_postMessage(
            channel=DEFAULT_CHANNEL,
            blocks=blocks,
            text=f"[SIMULATION COMPLETE] {scenario_name}",
        )
    except Exception:
        log.warning(
            "scenario_completed_card_post_failed", scenario_name=scenario_name, exc_info=True
        )
    log.info("scenario_completed_posted", scenario_name=scenario_name)


EVENT_HANDLERS: dict = {
    "task.created": handle_task_created,
    "task.claimed": handle_task_claimed,
    "task.completed": handle_task_completed,
    "ai.recommendation.generated": handle_ai_recommendation,
    "ai.output.approved": handle_ai_approved,
    "ai.output.rejected": handle_ai_rejected,
    "call.connected": handle_call_event,
    "call.missed": handle_call_event,
    "call.completed": handle_call_event,
    "scenario.started": handle_scenario_started,
    "scenario.completed": handle_scenario_completed,
}


async def run_consumer(
    slack_client,
    session_maker,
    bootstrap_servers: str,
    hasura_url: str,
    publisher=None,
    thread_manager=None,
) -> None:
    """Run the slack-bot consumer loop.

    Polls ocean.tasks, ocean.ai-ops, ocean.interactions, ocean.ops;
    dispatches to EVENT_HANDLERS, commits only on success.
    Logs and re-raises on unexpected error — the asyncio.create_task caller
    in main.py handles restarts.
    """
    conf = {**CONSUMER_CONFIG, "bootstrap.servers": bootstrap_servers}
    consumer = Consumer(conf)
    await consumer.subscribe(TOPICS)
    log.info("slack_bot_consumer_started", topics=TOPICS, brokers=bootstrap_servers)

    try:
        while True:
            msg = await consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error(
                    "consumer_error",
                    error=str(msg.error()),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
                continue

            try:
                event_data = json.loads(msg.value())
                event_type = event_data.get("event_type", "")
                handler = EVENT_HANDLERS.get(event_type)
                if handler:
                    await handler(
                        event_data,
                        slack_client=slack_client,
                        session_maker=session_maker,
                        hasura_url=hasura_url,
                        publisher=publisher,
                        thread_manager=thread_manager,
                    )
                else:
                    log.debug("event_type_skipped", event_type=event_type)
                await consumer.commit(message=msg)
            except Exception:
                log.exception(
                    "slack_bot_dispatch_failed_no_commit",
                    offset=msg.offset(),
                    topic=msg.topic(),
                    partition=msg.partition(),
                )
    except Exception:
        log.exception("slack_bot_consumer_fatal")
        raise
    finally:
        await consumer.close()
        log.info("slack_bot_consumer_closed")
