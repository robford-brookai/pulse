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
    cited_signals: list[str] | None = None,
) -> list[dict]:
    """Build the initial alert card posted to care team channel.

    Block layout (CONTEXT.md spec, Phase 4 upgrade):
      0: header   — "[{severity}] {alert_type title-cased}"
      1: section  — 4 mrkdwn fields (patient hash, severity, alert type, time)
      2: divider
      3: section  — AI summary text labeled "AI:"
      4: section  — Context signals citation
      5: divider
      6: actions  — Claim, Resolve, View Context buttons
    """
    if cited_signals is None:
        cited_signals = []

    header_text = f"[{severity}] {alert_type.replace('_', ' ').title()}"
    signals_text = f"_Context signals: {', '.join(cited_signals) if cited_signals else 'none'}_"

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
        # Block 3: AI summary (Phase 4: "AI:" label, not emoji)
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*AI:* {ai_summary}",
            },
        },
        # Block 4: context signals citation (Phase 4 addition)
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": signals_text,
            },
        },
        # Block 5: divider
        {"type": "divider"},
        # Block 6: actions
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


def outreach_draft_card(task_id: str, draft_id: str, draft_text: str) -> list[dict]:
    """Build the outreach draft card with Approve and Reject buttons.

    Human gate: no ZCC dispatch occurs without the Approve button being pressed.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*AI: Outreach Draft*\n_{draft_text}_\n\n"
                    "_Review and approve before dispatch._"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": f"outreach_actions_{draft_id}",
            "elements": [
                {
                    "type": "button",
                    "action_id": "outreach_approve",
                    "text": {"type": "plain_text", "text": "Approve & Dispatch", "emoji": False},
                    "style": "primary",
                    "value": draft_id,
                },
                {
                    "type": "button",
                    "action_id": "outreach_reject",
                    "text": {"type": "plain_text", "text": "Reject", "emoji": False},
                    "style": "danger",
                    "value": draft_id,
                },
            ],
        },
    ]


def approval_confirmed_card(draft_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after outreach draft is approved and dispatched."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[DISPATCHED] Outreach", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Outreach approved and dispatched by `{actor_id}`",
            },
        },
    ]


def rejection_confirmed_card(draft_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after outreach draft is rejected."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[REJECTED] Outreach Draft", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Draft rejected by `{actor_id}`",
            },
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
