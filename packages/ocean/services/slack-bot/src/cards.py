"""Slack Block Kit card builders."""
from __future__ import annotations


def alert_card(
    task_id: str,
    patient_hash: str,
    alert_type: str,
    severity: str,
    timestamp: str,
    ai_summary: str,
    hasura_url: str,
) -> list[dict]:
    """Build the initial alert card posted to care team channel.

    Block layout (CONTEXT.md spec):
      0: header   — "[{severity}] {alert_type title-cased}"
      1: section  — 4 mrkdwn fields (patient hash, severity, alert type, time)
      2: divider
      3: section  — AI summary text
      4: divider
      5: actions  — Claim, Resolve, View Context buttons
    """
    header_text = f"[{severity}] {alert_type.replace('_', ' ').title()}"

    return [
        # Block 0: header
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        # Block 1: detail fields
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Patient:*\n`{patient_hash}`"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                {"type": "mrkdwn", "text": f"*Alert Type:*\n{alert_type}"},
                {"type": "mrkdwn", "text": f"*Time:*\n{timestamp}"},
            ],
        },
        # Block 2: divider
        {"type": "divider"},
        # Block 3: AI summary
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🤖 AI Summary*\n_{ai_summary}_",
            },
        },
        # Block 4: divider
        {"type": "divider"},
        # Block 5: actions
        {
            "type": "actions",
            "block_id": f"task_actions_{task_id}",
            "elements": [
                {
                    "type": "button",
                    "action_id": "task_claim",
                    "text": {"type": "plain_text", "text": "Claim", "emoji": False},
                    "style": "primary",
                    "value": task_id,
                },
                {
                    "type": "button",
                    "action_id": "task_resolve",
                    "text": {"type": "plain_text", "text": "Resolve", "emoji": False},
                    "style": "danger",
                    "value": task_id,
                },
                {
                    "type": "button",
                    "action_id": "task_view_context",
                    "text": {"type": "plain_text", "text": "View Context", "emoji": False},
                    "url": hasura_url,
                    "value": task_id,
                },
            ],
        },
    ]


def claimed_card(task_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after a task is claimed. No action buttons."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[CLAIMED] Task", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Claimed by:*\n`{actor_id}`",
            },
        },
    ]


def resolved_card(task_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after a task is resolved. No action buttons."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[RESOLVED] Task", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Resolved by:*\n`{actor_id}`",
            },
        },
    ]
