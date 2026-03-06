"""Async Kafka consumer for slack-bot.

Reads from ocean.tasks; dispatches task.created events to post alert cards
to the routed Slack channel.

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
from src.cards import alert_card, outreach_draft_card

log = structlog.get_logger()

TOPICS = ["ocean.tasks"]

CONSUMER_CONFIG: dict = {
    "group.id": "slack-bot-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
}


async def handle_task_created(
    event_data: dict,
    *,
    slack_client,
    session_maker,
    hasura_url: str,
    publisher=None,
) -> None:
    """Handle task.created event: generate AI summary, build card, post to Slack.

    Phase 4 upgrade:
    - Calls generate_summary_with_context with Hasura graph context
    - Posts outreach draft card with Approve/Reject gate
    - Publishes ai.summary.generated and ai.response.drafted events
    """
    payload = event_data.get("payload", {})

    task_id = payload.get("task_id") or event_data.get("entity_id")
    patient_hash = payload.get("patient_id", "unknown")
    alert_type = payload.get("task_type", "unknown")
    severity = payload.get("priority", "routine").upper()
    timestamp = event_data.get("timestamp", "")
    channel = payload.get("channel", "#care-alerts-general")
    alert_id = payload.get("alert_id", "")

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

    await slack_client.chat_postMessage(
        channel=channel,
        blocks=blocks,
        text=f"[{severity}] {alert_type} alert",
    )

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
    draft_text = (
        f"Patient {patient_hash} has a {severity} {alert_type} alert. "
        "Please follow up."
    )

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


EVENT_HANDLERS: dict = {
    "task.created": handle_task_created,
}


async def run_consumer(
    slack_client,
    session_maker,
    bootstrap_servers: str,
    hasura_url: str,
    publisher=None,
) -> None:
    """Run the slack-bot consumer loop.

    Polls ocean.tasks, dispatches to EVENT_HANDLERS, commits only on success.
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
