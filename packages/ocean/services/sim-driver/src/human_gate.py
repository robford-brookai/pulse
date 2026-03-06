"""Human gate — posts low-confidence agent actions to #ocean-ops for review.

Uses httpx to call Slack's chat.postMessage API directly. Approval/override
buttons are handled by the existing bolt_app.py human_gate action handlers.
"""
from __future__ import annotations

import os

import httpx
import structlog

log = structlog.get_logger()

_OPS_CHANNEL = "#ocean-ops"


async def post_human_gate(
    patient_id: str,
    agent_id: str,
    action: str,
    alert_type: str,
    severity: str,
    score: float,
    reasoning: str,
    draft_id: str,
) -> None:
    """Post a structured message to #ocean-ops requesting human review.

    The message includes judge score, reasoning, and action context.
    Confirm/Override buttons reference the draft_id for the bolt_app handlers.
    """
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        log.warning("human_gate_no_slack_token", draft_id=draft_id)
        return

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[HUMAN GATE] Low-confidence action"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Agent:* {agent_id}"},
                {"type": "mrkdwn", "text": f"*Alert:* {severity} {alert_type}"},
                {"type": "mrkdwn", "text": f"*Action:* {action}"},
                {"type": "mrkdwn", "text": f"*Judge Score:* {score:.2f}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Judge reasoning:* {reasoning}"},
        },
        {
            "type": "actions",
            "block_id": f"human_gate_{draft_id}",
            "elements": [
                {
                    "type": "button",
                    "action_id": "human_gate_confirm",
                    "text": {"type": "plain_text", "text": "Confirm", "emoji": False},
                    "style": "primary",
                    "value": draft_id,
                },
                {
                    "type": "button",
                    "action_id": "human_gate_override",
                    "text": {"type": "plain_text", "text": "Override", "emoji": False},
                    "style": "danger",
                    "value": draft_id,
                },
            ],
        },
    ]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {slack_token}"},
                json={
                    "channel": _OPS_CHANNEL,
                    "text": f"[HUMAN GATE] Agent {agent_id} needs review (score={score:.2f})",
                    "blocks": blocks,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                log.warning("human_gate_slack_error", error=data.get("error"), draft_id=draft_id)
            else:
                log.info("human_gate_posted", draft_id=draft_id, score=score)
    except Exception:
        log.error("human_gate_post_failed", draft_id=draft_id)
        # Non-fatal — simulation continues
