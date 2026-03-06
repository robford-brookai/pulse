"""Slack Bolt action handlers — Claim, Resolve, Outreach Approve/Reject."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from src.ai_events import publish_ai_event
from src.cards import (
    approval_confirmed_card,
    claimed_card,
    outreach_draft_card,
    rejection_confirmed_card,
    resolved_card,
)
from src.zcc_dispatch import dispatch_zcc_outbound_call, get_zcc_oauth_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.publisher import RedpandaPublisher

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level injectable dependencies (set by main.py during lifespan)
# ---------------------------------------------------------------------------

_session_maker: "async_sessionmaker | None" = None
_publisher: "RedpandaPublisher | None" = None
_hasura_secret: str | None = None


def set_session_maker(sm: "async_sessionmaker") -> None:
    global _session_maker
    _session_maker = sm


def set_publisher(p: "RedpandaPublisher") -> None:
    global _publisher
    _publisher = p


def set_hasura_secret(s: str) -> None:
    global _hasura_secret
    _hasura_secret = s


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
# Action handlers — task claim and resolve
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


# ---------------------------------------------------------------------------
# Action handlers — outreach approve and reject (Phase 4)
# ---------------------------------------------------------------------------

@bolt_app.action("outreach_approve")
async def handle_outreach_approve(ack, body, client) -> None:
    """Handle outreach_approve button press.

    Ack-first (Slack 3-second timeout). Atomically marks draft approved,
    dispatches ZCC outbound call (stubbed if PHI_STORE_URL is absent),
    publishes ai.output.approved event, updates message with approval card.
    """
    await ack()

    draft_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("outreach_approve_received", draft_id=draft_id, actor_id=actor_id)

    row = None
    if _session_maker is not None:
        async with _session_maker() as session:
            result = await session.execute(
                sa.text(
                    "UPDATE ai_drafts "
                    "SET status='approved', actor_id=:actor_id, updated_at=now() "
                    "WHERE draft_id=:draft_id AND status='pending' "
                    "RETURNING draft_id, task_id, patient_id, alert_id"
                ),
                {"draft_id": draft_id, "actor_id": actor_id},
            )
            row = result.fetchone()
            await session.commit()

    if row is None:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=actor_id,
            text="This draft has already been processed.",
        )
        log.info("outreach_approve_already_processed", draft_id=draft_id)
        return

    task_id = row.task_id
    patient_id = row.patient_id

    await client.chat_postEphemeral(
        channel=channel_id,
        user=actor_id,
        text="Dispatching outreach...",
    )

    # Retrieve patient phone from PHI store (stub if not configured)
    phi_store_url = os.environ.get("PHI_STORE_URL", "")
    zcc_engagement_id = "stubbed"

    if phi_store_url:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10.0) as http:
            phone_resp = await http.get(f"{phi_store_url}/patients/{patient_id}/phone")
            phone_resp.raise_for_status()
            patient_phone = phone_resp.json().get("phone", "")

        zcc_token = await get_zcc_oauth_token(
            account_id=os.environ.get("ZCC_ACCOUNT_ID", ""),
            client_id=os.environ.get("ZCC_CLIENT_ID", ""),
            client_secret=os.environ.get("ZCC_CLIENT_SECRET", ""),
        )
        zcc_resp = await dispatch_zcc_outbound_call(
            zcc_token=zcc_token,
            agent_user_id=actor_id,
            patient_phone=patient_phone,
            queue_id=os.environ.get("ZCC_DEFAULT_QUEUE_ID", ""),
            task_id=task_id,
        )
        zcc_engagement_id = zcc_resp.get("engagement_id", "unknown")
    else:
        log.warning("phi_store_not_configured_zcc_stubbed", task_id=task_id)
        zcc_resp = await dispatch_zcc_outbound_call(
            zcc_token="stubbed",
            agent_user_id=actor_id,
            patient_phone="stubbed",
            queue_id=os.environ.get("ZCC_DEFAULT_QUEUE_ID", ""),
            task_id=task_id,
        )
        zcc_engagement_id = zcc_resp.get("zcc_engagement_id", "stubbed")

    await publish_ai_event(
        publisher=_publisher,
        event_type="ai.output.approved",
        task_id=task_id,
        patient_id=patient_id,
        payload={
            "draft_id": draft_id,
            "actor_id": actor_id,
            "zcc_engagement_id": zcc_engagement_id,
        },
    )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=approval_confirmed_card(draft_id, actor_id),
        text=f"Outreach approved and dispatched by {actor_id}",
    )
    log.info("outreach_approved_dispatched", draft_id=draft_id, actor_id=actor_id)


@bolt_app.action("outreach_reject")
async def handle_outreach_reject(ack, body, client) -> None:
    """Handle outreach_reject button press.

    Ack-first. Atomically marks draft rejected, publishes ai.output.rejected event,
    updates message with rejection card. Rejection is always auditable.
    """
    await ack()

    draft_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("outreach_reject_received", draft_id=draft_id, actor_id=actor_id)

    row = None
    if _session_maker is not None:
        async with _session_maker() as session:
            result = await session.execute(
                sa.text(
                    "UPDATE ai_drafts "
                    "SET status='rejected', actor_id=:actor_id, updated_at=now() "
                    "WHERE draft_id=:draft_id AND status='pending' "
                    "RETURNING draft_id, task_id, patient_id"
                ),
                {"draft_id": draft_id, "actor_id": actor_id},
            )
            row = result.fetchone()
            await session.commit()

    if row is None:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=actor_id,
            text="Already processed.",
        )
        log.info("outreach_reject_already_processed", draft_id=draft_id)
        return

    task_id = getattr(row, "task_id", "unknown")
    patient_id = getattr(row, "patient_id", "unknown")

    await publish_ai_event(
        publisher=_publisher,
        event_type="ai.output.rejected",
        task_id=task_id,
        patient_id=patient_id,
        payload={
            "draft_id": draft_id,
            "actor_id": actor_id,
        },
    )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=rejection_confirmed_card(draft_id, actor_id),
        text=f"Draft rejected by {actor_id}",
    )
    log.info("outreach_rejected", draft_id=draft_id, actor_id=actor_id)
