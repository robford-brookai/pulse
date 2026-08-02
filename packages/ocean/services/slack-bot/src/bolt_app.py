"""Slack Bolt action handlers — Claim, Resolve, Outreach Approve/Reject, Ticket Create."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
import structlog
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from src.ai_events import publish_ai_event
from src.cards import (
    approval_confirmed_card,
    claimed_card,
    delivery_claimed_card,
    delivery_resolved_card,
    human_gate_confirmed_card,
    human_gate_overridden_card,
    rejection_confirmed_card,
    resolved_card,
    snoozed_card,
    snooze_duration_card,
    ticket_claimed_card,
    ticket_resolved_card,
)
from src.slash_commands import CATEGORY_CHANNEL_MAP, build_ticket_modal, handle_ocean_command
from src.zcc_dispatch import dispatch_zcc_outbound_call, get_zcc_oauth_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.publisher import RedpandaPublisher

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level injectable dependencies (set by main.py during lifespan)
# ---------------------------------------------------------------------------

_session_maker: async_sessionmaker | None = None
_publisher: RedpandaPublisher | None = None
_hasura_secret: str | None = None


def set_session_maker(sm: async_sessionmaker) -> None:
    global _session_maker
    _session_maker = sm


def set_publisher(p: RedpandaPublisher) -> None:
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

# Register /ocean slash command
bolt_app.command("/ocean")(handle_ocean_command)


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
                    "timestamp": datetime.now(UTC).isoformat(),
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
    timestamp = datetime.now(UTC).isoformat()

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
# Action handlers — alert snooze (Phase 23 / ALRT-01)
# ---------------------------------------------------------------------------

# Duration labels keyed by minutes for confirmation card
_SNOOZE_LABELS: dict[int, str] = {
    15: "15 minutes",
    60: "1 hour",
    240: "4 hours",
    480: "8 hours",
    1440: "24 hours",
}


@bolt_app.action("task_snooze")
async def handle_task_snooze(ack, body, client) -> None:
    """Handle Snooze button press — show ephemeral duration picker."""
    await ack()

    task_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]

    log.info("task_snooze_received", task_id=task_id, actor_id=actor_id)

    await client.chat_postEphemeral(
        channel=channel_id,
        user=actor_id,
        blocks=snooze_duration_card(task_id),
        text="Select snooze duration",
    )


@bolt_app.action("snooze_confirm")
async def handle_snooze_confirm(ack, body, client) -> None:
    """Handle snooze duration selection — persist snooze, publish event, update card."""
    await ack()

    selected = body["actions"][0]["selected_option"]["value"]
    task_id, minutes_str = selected.rsplit(":", 1)
    minutes = int(minutes_str)
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("snooze_confirm_received", task_id=task_id, minutes=minutes, actor_id=actor_id)

    # Persist snooze to DB
    alert_id: str | None = None
    if _session_maker is not None:
        async with _session_maker() as session:
            # Look up alert_id from task
            result = await session.execute(
                sa.text("SELECT alert_id FROM tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            row = result.fetchone()
            alert_id = row.alert_id if row else task_id

            await session.execute(
                sa.text(
                    "INSERT INTO alert_snoozes (alert_id, snoozed_by, snooze_until, reason) "
                    "VALUES (:alert_id, :snoozed_by, now() + make_interval(mins => :minutes), 'user_snooze') "
                    "ON CONFLICT (alert_id) WHERE (active) DO UPDATE SET "
                    "  snoozed_by = EXCLUDED.snoozed_by, "
                    "  snoozed_at = now(), "
                    "  snooze_until = EXCLUDED.snooze_until"
                ),
                {"alert_id": alert_id, "snoozed_by": actor_id, "minutes": minutes},
            )
            await session.commit()

    duration_label = _SNOOZE_LABELS.get(minutes, f"{minutes} minutes")

    # Publish alert.snoozed event
    if _publisher is not None:
        await _publisher.publish(
            "ocean.tasks",
            {
                "event_type": "alert.snoozed",
                "entity_id": alert_id or task_id,
                "entity_type": "alert",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "task_id": task_id,
                    "alert_id": alert_id or task_id,
                    "snoozed_by": actor_id,
                    "duration_minutes": minutes,
                },
            },
        )

    # Update original message with snoozed confirmation card
    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=snoozed_card(task_id, duration_label, actor_id),
        text=f"Alert snoozed for {duration_label}",
    )
    log.info("alert_snoozed", task_id=task_id, alert_id=alert_id, duration=duration_label)


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


# ---------------------------------------------------------------------------
# Action handlers — human gate confirm and override (Phase 5)
# ---------------------------------------------------------------------------

@bolt_app.action("human_gate_confirm")
async def handle_human_gate_confirm(ack, body, client) -> None:
    """Handle human_gate_confirm button press from sim-driver human gate.

    Ack-first. Updates message with confirmed card, publishes ai.output.confirmed event.
    """
    await ack()

    draft_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("human_gate_confirm_received", draft_id=draft_id, actor_id=actor_id)

    await publish_ai_event(
        publisher=_publisher,
        event_type="ai.output.confirmed",
        task_id=draft_id,
        patient_id="unknown",
        payload={
            "draft_id": draft_id,
            "actor_id": actor_id,
        },
    )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=human_gate_confirmed_card(draft_id, actor_id),
        text=f"Human gate confirmed by {actor_id}",
    )
    log.info("human_gate_confirmed", draft_id=draft_id, actor_id=actor_id)


@bolt_app.action("human_gate_override")
async def handle_human_gate_override(ack, body, client) -> None:
    """Handle human_gate_override button press from sim-driver human gate.

    Ack-first. Updates message with override card, publishes ai.output.overridden event.
    """
    await ack()

    draft_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("human_gate_override_received", draft_id=draft_id, actor_id=actor_id)

    await publish_ai_event(
        publisher=_publisher,
        event_type="ai.output.overridden",
        task_id=draft_id,
        patient_id="unknown",
        payload={
            "draft_id": draft_id,
            "actor_id": actor_id,
        },
    )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=human_gate_overridden_card(draft_id, actor_id),
        text=f"Human gate overridden by {actor_id}",
    )
    log.info("human_gate_overridden", draft_id=draft_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Action handlers — ticket claim, resolve, wait, resume (Phase 17)
# ---------------------------------------------------------------------------

@bolt_app.action("ticket_claim")
async def handle_ticket_claim(ack, body, client) -> None:
    """Handle ticket_claim button — optimistic update + publish request event."""
    await ack()

    ticket_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("ticket_claim_received", ticket_id=ticket_id, actor_id=actor_id)

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tickets",
            {
                "event_type": "ticket.update.requested",
                "entity_id": ticket_id,
                "entity_type": "ticket",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "ticket_id": ticket_id,
                    "new_status": "in_progress",
                    "actor_user_id": actor_id,
                },
            },
        )

    # Optimistic card update
    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=ticket_claimed_card(ticket_id, ticket_id, actor_id),
        text=f"Ticket claimed by {actor_id}",
    )
    log.info("ticket_claimed", ticket_id=ticket_id, actor_id=actor_id)


@bolt_app.action("ticket_resolve")
async def handle_ticket_resolve(ack, body, client) -> None:
    """Handle ticket_resolve button — optimistic update + publish request event."""
    await ack()

    ticket_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("ticket_resolve_received", ticket_id=ticket_id, actor_id=actor_id)

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tickets",
            {
                "event_type": "ticket.update.requested",
                "entity_id": ticket_id,
                "entity_type": "ticket",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "ticket_id": ticket_id,
                    "new_status": "resolved",
                    "actor_user_id": actor_id,
                },
            },
        )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=ticket_resolved_card(ticket_id, ticket_id, actor_id, ""),
        text=f"Ticket resolved by {actor_id}",
    )
    log.info("ticket_resolved", ticket_id=ticket_id, actor_id=actor_id)


@bolt_app.action("ticket_wait")
async def handle_ticket_wait(ack, body, client) -> None:
    """Handle ticket_wait button — open modal for waiting reason selection."""
    await ack()

    ticket_id: str = body["actions"][0]["value"]
    trigger_id: str = body["trigger_id"]

    log.info("ticket_wait_received", ticket_id=ticket_id)

    await client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "ticket_wait_modal",
            "private_metadata": ticket_id,
            "title": {"type": "plain_text", "text": "Set Waiting Reason"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "waiting_reason_block",
                    "element": {
                        "type": "static_select",
                        "action_id": "waiting_reason_select",
                        "placeholder": {"type": "plain_text", "text": "Select reason"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "External Block"},
                                "value": "external_block",
                            },
                            {
                                "text": {"type": "plain_text", "text": "Timed Pause"},
                                "value": "timed_pause",
                            },
                            {
                                "text": {"type": "plain_text", "text": "Patient Response"},
                                "value": "patient_response",
                            },
                        ],
                    },
                    "label": {"type": "plain_text", "text": "Waiting Reason"},
                },
            ],
        },
    )


@bolt_app.view("ticket_wait_modal")
async def handle_ticket_wait_modal(ack, body, client) -> None:
    """Handle ticket_wait_modal submission — publish waiting event."""
    await ack()

    ticket_id: str = body["view"]["private_metadata"]
    actor_id: str = body["user"]["id"]
    values = body["view"]["state"]["values"]
    selected = values["waiting_reason_block"]["waiting_reason_select"]
    waiting_reason = selected["selected_option"]["value"]

    log.info("ticket_wait_modal_submitted", ticket_id=ticket_id, reason=waiting_reason)

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tickets",
            {
                "event_type": "ticket.update.requested",
                "entity_id": ticket_id,
                "entity_type": "ticket",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "ticket_id": ticket_id,
                    "new_status": "waiting",
                    "waiting_reason": waiting_reason,
                    "actor_user_id": actor_id,
                },
            },
        )


@bolt_app.action("ticket_resume")
async def handle_ticket_resume(ack, body, client) -> None:
    """Handle ticket_resume button — resume from waiting state."""
    await ack()

    ticket_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("ticket_resume_received", ticket_id=ticket_id, actor_id=actor_id)

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tickets",
            {
                "event_type": "ticket.update.requested",
                "entity_id": ticket_id,
                "entity_type": "ticket",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "ticket_id": ticket_id,
                    "new_status": "in_progress",
                    "actor_user_id": actor_id,
                },
            },
        )

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=ticket_claimed_card(ticket_id, ticket_id, actor_id),
        text=f"Ticket resumed by {actor_id}",
    )
    log.info("ticket_resumed", ticket_id=ticket_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Ticket creation modal submission + message shortcut (Phase 17 Plan 02)
# ---------------------------------------------------------------------------

OPS_CHANNEL = os.environ.get("OPS_SLACK_CHANNEL", "#care-alerts-ops")


@bolt_app.view("ticket_create_modal")
async def handle_ticket_create_modal(ack, body, client) -> None:
    """Handle ticket_create_modal submission.

    Publishes ticket.create.requested to ocean.tickets and sends ephemeral
    routing confirmation. human_id is NOT included — control-plane assigns
    it asynchronously after processing the event.
    """
    await ack()

    view = body["view"]
    user_id = body["user"]["id"]
    values = view["state"]["values"]

    category = values["category_block"]["category_select"]["selected_option"]["value"]
    description = values["description_block"]["description_input"]["value"]
    priority = values["priority_block"]["priority_select"]["selected_option"]["value"]
    patient_id = (values["patient_block"]["patient_input"].get("value") or "")
    related_ticket = (values["related_block"]["related_input"].get("value") or "")

    # Parse private_metadata for source_message_url
    try:
        metadata = json.loads(view.get("private_metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    source_message_url = metadata.get("source_message_url")

    now = datetime.now(UTC)
    event = {
        "event_id": str(uuid4()),
        "event_type": "ticket.create.requested",
        "schema_version": "1.0.0",
        "timestamp": now.isoformat(),
        "source_system": "slack-bot",
        "entity_type": "ticket",
        "correlation_id": str(uuid4()),
        "payload": {
            "category": category,
            "priority": priority,
            "description": description,
            "patient_id": patient_id,
            "source_message_url": source_message_url,
            "creator_slack_id": user_id,
            "related_ticket_human_id": related_ticket,
            "task_ids": [],
            "alert_ids": [],
        },
    }

    if _publisher is not None:
        await _publisher.publish("ocean.tickets", event)

    channel = CATEGORY_CHANNEL_MAP.get(category, "#ocean-devices")
    await client.chat_postEphemeral(
        channel=OPS_CHANNEL,
        user=user_id,
        text=f"Ticket request submitted, routing to {channel}...",
    )
    log.info("ticket_create_modal_submitted", category=category, user=user_id)


async def handle_create_ocean_ticket_shortcut(ack, body, client) -> None:
    """Handle 'Create Ocean Ticket' message shortcut / action.

    Opens ticket modal with description pre-filled from message text
    and source_message_url stored in private_metadata.
    """
    await ack()

    message = body.get("message", {})
    message_text = message.get("text", "")
    channel_id = body.get("channel", {}).get("id", "")
    message_ts = message.get("ts", "")

    # Get permalink for the source message
    source_message_url = None
    if channel_id and message_ts:
        try:
            result = await client.chat_getPermalink(channel=channel_id, message_ts=message_ts)
            source_message_url = result.get("permalink")
        except Exception:
            log.warning("permalink_fetch_failed", channel=channel_id, ts=message_ts)

    metadata = json.dumps({
        "source_message_url": source_message_url,
    })

    modal = build_ticket_modal(
        private_metadata=metadata,
        prefill_description=message_text,
    )

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=modal,
    )
    log.info("ticket_shortcut_opened", channel=channel_id)


# Register message shortcut and action
bolt_app.shortcut("create_ocean_ticket")(handle_create_ocean_ticket_shortcut)
bolt_app.action("create_ocean_ticket")(handle_create_ocean_ticket_shortcut)


# ---------------------------------------------------------------------------
# RMA action handlers (Phase 19)
# ---------------------------------------------------------------------------


async def _lookup_rma_context(ticket_id: str) -> dict:
    """Look up patient, device, and order info for RMA modal from graph DB."""
    result = {"ticket_id": ticket_id, "patient_id": "", "device_id": "", "order_id": ""}
    if _session_maker is None:
        return result

    async with _session_maker() as session:
        # Get patient_id from ticket
        ticket_result = await session.execute(
            sa.text("SELECT patient_id FROM tickets WHERE ticket_id = :ticket_id"),
            {"ticket_id": ticket_id},
        )
        row = ticket_result.fetchone()
        if row is None:
            return result
        patient_id = row.patient_id
        result["patient_id"] = patient_id

        # Get order_id from fulfillments
        ful_result = await session.execute(
            sa.text(
                "SELECT order_id FROM fulfillments "
                "WHERE patient_id = :patient_id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"patient_id": patient_id},
        )
        result["order_id"] = ful_result.scalar_one_or_none() or ""

        # Get device_id from device_associations
        dev_result = await session.execute(
            sa.text(
                "SELECT device_id FROM device_associations "
                "WHERE patient_id = :patient_id AND status = 'active' LIMIT 1"
            ),
            {"patient_id": patient_id},
        )
        result["device_id"] = dev_result.scalar_one_or_none() or ""

    return result


def _build_rma_modal(metadata: dict) -> dict:
    """Build the RMA creation modal view."""
    return {
        "type": "modal",
        "callback_id": "rma_create_modal",
        "private_metadata": json.dumps(metadata),
        "title": {"type": "plain_text", "text": "Create RMA"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*Patient:* `{metadata.get('patient_id', '')}`  |  "
                            f"*Device:* `{metadata.get('device_id', '')}`  |  "
                            f"*Order:* `{metadata.get('order_id', '')}`"
                        ),
                    },
                ],
            },
            {
                "type": "input",
                "block_id": "reason_block",
                "element": {
                    "type": "static_select",
                    "action_id": "reason_select",
                    "placeholder": {"type": "plain_text", "text": "Select reason"},
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "Defective"},
                            "value": "defective",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Wrong Device"},
                            "value": "wrong_device",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Patient Request"},
                            "value": "patient_request",
                        },
                        {
                            "text": {"type": "plain_text", "text": "Other"},
                            "value": "other",
                        },
                    ],
                },
                "label": {"type": "plain_text", "text": "Return Reason"},
            },
        ],
    }


@bolt_app.action("ticket_create_rma")
async def handle_ticket_create_rma(ack, body, client) -> None:
    """Handle Create RMA button — open modal with pre-populated patient/device/order data."""
    await ack()

    ticket_id: str = body["actions"][0]["value"]
    trigger_id: str = body["trigger_id"]

    log.info("ticket_create_rma_received", ticket_id=ticket_id)

    metadata = await _lookup_rma_context(ticket_id)
    modal = _build_rma_modal(metadata)

    await client.views_open(trigger_id=trigger_id, view=modal)


@bolt_app.view("rma_create_modal")
async def handle_rma_create_modal(ack, body, client) -> None:
    """Handle RMA modal submission — publish ticket.rma.requested event."""
    await ack()

    view = body["view"]
    user_id = body["user"]["id"]
    values = view["state"]["values"]
    reason = values["reason_block"]["reason_select"]["selected_option"]["value"]

    try:
        metadata = json.loads(view.get("private_metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    ticket_id = metadata.get("ticket_id", "")
    patient_id = metadata.get("patient_id", "")
    device_id = metadata.get("device_id", "")
    order_id = metadata.get("order_id", "")

    log.info("rma_modal_submitted", ticket_id=ticket_id, reason=reason)

    if _publisher is not None:
        now = datetime.now(UTC)
        event = {
            "event_id": str(uuid4()),
            "event_type": "ticket.rma.requested",
            "schema_version": "1.0.0",
            "timestamp": now.isoformat(),
            "source_system": "slack-bot",
            "entity_id": ticket_id,
            "entity_type": "ticket",
            "correlation_id": str(uuid4()),
            "payload": {
                "ticket_id": ticket_id,
                "patient_id": patient_id,
                "device_id": device_id,
                "order_id": order_id,
                "reason": reason,
            },
        }
        await _publisher.publish("ocean.tickets", event)

    await client.chat_postEphemeral(
        channel=OPS_CHANNEL,
        user=user_id,
        text=f"RMA request submitted for {ticket_id}",
    )


@bolt_app.action("ticket_retry_rma")
async def handle_ticket_retry_rma(ack, body, client) -> None:
    """Handle Retry RMA button — re-open RMA modal with same context."""
    await ack()

    ticket_id: str = body["actions"][0]["value"]
    trigger_id: str = body["trigger_id"]

    log.info("ticket_retry_rma_received", ticket_id=ticket_id)

    metadata = await _lookup_rma_context(ticket_id)
    modal = _build_rma_modal(metadata)

    await client.views_open(trigger_id=trigger_id, view=modal)


# ---------------------------------------------------------------------------
# Delivery action handlers (Phase 19 Plan 02)
# ---------------------------------------------------------------------------


@bolt_app.action("delivery_claim")
async def handle_delivery_claim(ack, body, client) -> None:
    """Handle delivery_claim button — update card, post thread reply, publish event."""
    await ack()

    order_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("delivery_claim_received", order_id=order_id, actor_id=actor_id)

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=delivery_claimed_card(order_id, order_id, "Device", actor_id),
        text=f"Delivery claimed by {actor_id}",
    )

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=message_ts,
        text=f"Claimed by <@{actor_id}> -- ready for patient onboarding call",
        reply_broadcast=False,
    )

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tickets",
            {
                "event_type": "delivery.claimed",
                "entity_id": order_id,
                "entity_type": "fulfillment",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "order_id": order_id,
                    "actor_id": actor_id,
                },
            },
        )

    log.info("delivery_claimed", order_id=order_id, actor_id=actor_id)


@bolt_app.action("delivery_resolve")
async def handle_delivery_resolve(ack, body, client) -> None:
    """Handle delivery_resolve button — mark handoff complete."""
    await ack()

    order_id: str = body["actions"][0]["value"]
    actor_id: str = body["user"]["id"]
    channel_id: str = body["container"]["channel_id"]
    message_ts: str = body["container"]["message_ts"]

    log.info("delivery_resolve_received", order_id=order_id, actor_id=actor_id)

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=delivery_resolved_card(order_id, order_id, "Device", actor_id),
        text="Delivery handoff complete",
    )

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=message_ts,
        text="Handoff complete",
        reply_broadcast=False,
    )

    if _publisher is not None:
        await _publisher.publish(
            "ocean.tickets",
            {
                "event_type": "delivery.resolved",
                "entity_id": order_id,
                "entity_type": "fulfillment",
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": {
                    "order_id": order_id,
                    "actor_id": actor_id,
                },
            },
        )

    log.info("delivery_resolved", order_id=order_id, actor_id=actor_id)
