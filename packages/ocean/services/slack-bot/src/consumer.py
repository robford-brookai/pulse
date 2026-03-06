"""Async Kafka consumer for slack-bot.

Reads from ocean.tasks; dispatches task.created events to post alert cards
to the routed Slack channel.

Consumer group: slack-bot-worker (receives events independently of other consumers).
Manual offset commit — offset committed only AFTER successful handler return.
"""
from __future__ import annotations

import json

import structlog
from confluent_kafka import KafkaError
from confluent_kafka.aio import AIOConsumer as Consumer

from src.ai_summary import generate_summary
from src.cards import alert_card

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
) -> None:
    """Handle task.created event: generate AI summary, build card, post to Slack."""
    payload = event_data.get("payload", {})

    task_id = payload.get("task_id") or event_data.get("entity_id")
    patient_hash = payload.get("patient_id", "unknown")
    alert_type = payload.get("task_type", "unknown")
    severity = payload.get("priority", "routine").upper()
    timestamp = event_data.get("timestamp", "")
    channel = payload.get("channel", "#care-alerts-general")

    ai_summary = await generate_summary(alert_type, severity, patient_hash, timestamp)
    blocks = alert_card(task_id, patient_hash, alert_type, severity, timestamp, ai_summary, hasura_url)

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


EVENT_HANDLERS: dict = {
    "task.created": handle_task_created,
}


async def run_consumer(
    slack_client,
    session_maker,
    bootstrap_servers: str,
    hasura_url: str,
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
