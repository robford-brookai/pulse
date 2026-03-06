"""Slack Bolt action handlers — Claim and Resolve interactions."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from src.cards import claimed_card, resolved_card

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.publisher import RedpandaPublisher

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level injectable dependencies (set by main.py during lifespan)
# ---------------------------------------------------------------------------

_session_maker: "async_sessionmaker | None" = None
_publisher: "RedpandaPublisher | None" = None


def set_session_maker(sm: "async_sessionmaker") -> None:
    global _session_maker
    _session_maker = sm


def set_publisher(p: "RedpandaPublisher") -> None:
    global _publisher
    _publisher = p


# ---------------------------------------------------------------------------
# Bolt app (initialized with env vars — token may be empty during tests
# but handlers are only invoked when Slack sends actual requests)
# ---------------------------------------------------------------------------

bolt_app = AsyncApp(
    token=os.environ.get("SLACK_BOT_TOKEN", "xoxb-test-token"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET", "test-secret"),
)
bolt_handler = AsyncSlackRequestHandler(bolt_app)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

@bolt_app.action("task_claim")
async def handle_task_claim(ack, body, client) -> None:
    """Handle task_claim button press.

    1. ack() MUST be first — Slack 3-second timeout.
    2. Atomic UPDATE WHERE status='open' RETURNING task_id — idempotent claim.
    3. On success: chat_update with claimed_card, publish task.claimed event.
    4. On duplicate: chat_postEphemeral with rejection message.
    """
    await ack()

    task_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("task_claim_received", task_id=task_id, actor_id=actor_id)

    claimed = False
    if _session_maker is not None:
        async with _session_maker() as session:
            result = await session.execute(
                sa.text(
                    "UPDATE tasks "
                    "SET status='claimed', assigned_to=:actor_id, updated_at=now() "
                    "WHERE task_id=:task_id AND status='open' "
                    "RETURNING task_id"
                ),
                {"task_id": task_id, "actor_id": actor_id},
            )
            row = result.fetchone()
            claimed = row is not None
            await session.commit()

    if claimed:
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=claimed_card(task_id, actor_id),
            text=f"Task claimed by {actor_id}",
        )
        log.info("task_claimed", task_id=task_id, actor_id=actor_id)

        if _publisher is not None:
            await _publisher.publish(
                "ocean.tasks",
                {
                    "event_type": "task.claimed",
                    "entity_id": task_id,
                    "entity_type": "task",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {"task_id": task_id, "actor_id": actor_id},
                },
            )
    else:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=actor_id,
            text="This task has already been claimed by another coordinator.",
        )
        log.info("task_claim_rejected_already_claimed", task_id=task_id, actor_id=actor_id)


@bolt_app.action("task_resolve")
async def handle_task_resolve(ack, body, client) -> None:
    """Handle task_resolve button press.

    1. ack() MUST be first — Slack 3-second timeout.
    2. UPDATE tasks SET status='completed'.
    3. Publish task.completed event to ocean.tasks (task_id, actor_id, timestamp).
    4. chat_update with resolved_card.
    """
    await ack()

    task_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]
    timestamp = datetime.now(timezone.utc).isoformat()

    log.info("task_resolve_received", task_id=task_id, actor_id=actor_id)

    if _session_maker is not None:
        async with _session_maker() as session:
            await session.execute(
                sa.text(
                    "UPDATE tasks "
                    "SET status='completed', assigned_to=:actor_id, updated_at=now() "
                    "WHERE task_id=:task_id"
                ),
                {"task_id": task_id, "actor_id": actor_id},
            )
            await session.commit()

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tasks",
            {
                "event_type": "task.completed",
                "entity_id": task_id,
                "entity_type": "task",
                "timestamp": timestamp,
                "payload": {
                    "task_id": task_id,
                    "actor_id": actor_id,
                    "resolution": "resolved",
                },
            },
        )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=resolved_card(task_id, actor_id),
        text=f"Task resolved by {actor_id}",
    )
    log.info("task_resolved", task_id=task_id, actor_id=actor_id)
