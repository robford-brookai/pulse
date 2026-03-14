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
    status: str | None = None,
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

    Phase 15: optional status parameter prepends [STATUS] to header.
    """
    if cited_signals is None:
        cited_signals = []

    header_text = f"[{severity}] {alert_type.replace('_', ' ').title()}"
    if status:
        header_text = f"[{status.upper()}] {header_text}"
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
                    f"*AI: Outreach Draft*\n_{draft_text}_\n\n_Review and approve before dispatch._"
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


def human_gate_confirmed_card(draft_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after a human gate action is confirmed."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[CONFIRMED] Human Gate", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Action confirmed by `{actor_id}`\nDraft: `{draft_id}`",
            },
        },
    ]


def human_gate_overridden_card(draft_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after a human gate action is overridden."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[OVERRIDDEN] Human Gate", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Action overridden by `{actor_id}`\nDraft: `{draft_id}`",
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


def lifecycle_update_blocks(updates: list[dict]) -> list[dict]:
    """Build consolidated Block Kit blocks from a batch of lifecycle events.

    Each update gets a section with event type header and relevant fields.
    Dividers separate multiple updates. Supported types: claimed,
    ai_recommendation, ai_approved, ai_rejected, call_outcome, task_completed.
    """
    blocks: list[dict] = []

    for i, update in enumerate(updates):
        if i > 0:
            blocks.append({"type": "divider"})

        update_type = update.get("type", "update")

        if update_type == "claimed":
            actor = update.get("actor", "Unknown")
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Task Claimed*\nClaimed by `{actor}`",
                    },
                }
            )

        elif update_type == "ai_recommendation":
            action = update.get("action", "")
            confidence = update.get("confidence", "")
            reasoning = update.get("reasoning", "")
            text = f"*AI Recommendation*\n*Action:* {action}\n*Confidence:* {confidence}"
            if reasoning:
                text += f"\n_Reasoning: {reasoning}_"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            )

        elif update_type == "ai_approved":
            actor = update.get("actor", "Unknown")
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*AI Output Approved*\nApproved by `{actor}`",
                    },
                }
            )

        elif update_type == "ai_rejected":
            actor = update.get("actor", "Unknown")
            reason = update.get("reason", "")
            text = f"*AI Output Rejected*\nRejected by `{actor}`"
            if reason:
                text += f"\n_Reason: {reason}_"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            )

        elif update_type == "call_outcome":
            outcome = update.get("outcome", "unknown")
            duration = update.get("duration_seconds")
            text = f"*Call Outcome*\nOutcome: {outcome}"
            if duration is not None:
                text += f"\nDuration: {duration}s"
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            )

        elif update_type == "task_completed":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Task Completed*\nTask has been resolved.",
                    },
                }
            )

        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{update_type}*"},
                }
            )

    return blocks


# ---------------------------------------------------------------------------
# Ticket card builders (Phase 17)
# ---------------------------------------------------------------------------

STATUS_EMOJIS: dict[str, str] = {
    "open": ":large_green_circle:",
    "in_progress": ":large_yellow_circle:",
    "waiting": ":large_orange_circle:",
    "resolved": ":white_check_mark:",
}

PRIORITY_EMOJIS: dict[str, str] = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":white_circle:",
}

# Buttons per ticket status
_TICKET_BUTTONS: dict[str, list[tuple[str, str, str | None]]] = {
    # (action_id, label, style)
    "open": [
        ("ticket_claim", "Claim", "primary"),
        ("ticket_resolve", "Resolve", "danger"),
        ("ticket_wait", "Wait", None),
    ],
    "in_progress": [
        ("ticket_resolve", "Resolve", "danger"),
        ("ticket_wait", "Wait", None),
    ],
    "waiting": [
        ("ticket_resume", "Resume", "primary"),
        ("ticket_resolve", "Resolve", "danger"),
    ],
}


def _ticket_action_buttons(
    ticket_id: str, status: str, category: str | None = None
) -> list[dict]:
    """Build action button elements for a given ticket status.

    When status is in_progress and category is device_issue, appends a
    "Create RMA" button for Impilo return initiation.
    """
    buttons = _TICKET_BUTTONS.get(status, [])
    elements = []
    for action_id, label, style in buttons:
        btn: dict = {
            "type": "button",
            "action_id": action_id,
            "text": {"type": "plain_text", "text": label, "emoji": False},
            "value": ticket_id,
        }
        if style:
            btn["style"] = style
        elements.append(btn)

    if status == "in_progress" and category == "device_issue":
        elements.append(
            {
                "type": "button",
                "action_id": "ticket_create_rma",
                "text": {"type": "plain_text", "text": "Create RMA", "emoji": False},
                "style": "primary",
                "value": ticket_id,
            }
        )

    return elements


def ticket_card(
    ticket_id: str,
    human_id: str,
    category: str,
    priority: str,
    status: str,
    description: str,
    ai_summary: str,
    patient_id: str | None = None,
    creator_id: str | None = None,
    rma_status: str | None = None,
    rma_return_id: str | None = None,
) -> list[dict]:
    """Build a ticket card with status-dependent action buttons.

    Block layout:
      0: header  — status_emoji + human_id + STATUS (with [RMA] badge if rma_return_id)
      1: section — 4-5 mrkdwn fields (category, priority, patient, creator, +RMA status)
      2: divider
      3: section — description
      4: section — AI summary ("AI: ...")
      5: divider
      6: actions — buttons based on status (omitted for resolved)
    """
    status_emoji = STATUS_EMOJIS.get(status, "")
    priority_emoji = PRIORITY_EMOJIS.get(priority, "")
    header_text = f"{status_emoji} {human_id} [{status.upper()}]"
    if rma_return_id:
        header_text = f"[RMA] {header_text}"

    fields = [
        {"type": "mrkdwn", "text": f"*Category:*\n{category}"},
        {"type": "mrkdwn", "text": f"*Priority:*\n{priority_emoji} {priority}"},
        {"type": "mrkdwn", "text": f"*Patient:*\n`{patient_id or 'unknown'}`"},
        {
            "type": "mrkdwn",
            "text": f"*Creator:*\n<@{creator_id}>" if creator_id else "*Creator:*\nunknown",
        },
    ]
    if rma_status:
        fields.append({"type": "mrkdwn", "text": f"*RMA:*\n{rma_status}"})

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "fields": fields,
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": description},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*AI:* {ai_summary}"},
        },
        {"type": "divider"},
    ]

    elements = _ticket_action_buttons(ticket_id, status, category=category)
    if elements:
        blocks.append(
            {
                "type": "actions",
                "block_id": f"ticket_actions_{ticket_id}",
                "elements": elements,
            }
        )

    return blocks


def ticket_claimed_card(
    ticket_id: str,
    human_id: str,
    actor_id: str,
    rma_return_id: str | None = None,
) -> list[dict]:
    """Card shown after a ticket is claimed — IN PROGRESS state."""
    header_text = f":large_yellow_circle: {human_id} [IN PROGRESS]"
    if rma_return_id:
        header_text = f"[RMA] {header_text}"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Claimed by <@{actor_id}>"},
            ],
        },
        {
            "type": "actions",
            "block_id": f"ticket_actions_{ticket_id}",
            "elements": _ticket_action_buttons(ticket_id, "in_progress"),
        },
    ]


def ticket_waiting_card(
    ticket_id: str, human_id: str, waiting_reason: str
) -> list[dict]:
    """Card shown when a ticket enters waiting state."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":large_orange_circle: {human_id} [WAITING]",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Reason: {waiting_reason}"},
            ],
        },
        {
            "type": "actions",
            "block_id": f"ticket_actions_{ticket_id}",
            "elements": _ticket_action_buttons(ticket_id, "waiting"),
        },
    ]


def ticket_resolved_card(
    ticket_id: str, human_id: str, actor_id: str, duration_str: str
) -> list[dict]:
    """Card shown when a ticket is resolved — no action buttons."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":white_check_mark: {human_id} [RESOLVED]",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Resolved by <@{actor_id}> ({duration_str})"},
            ],
        },
    ]


def scenario_started_card(
    scenario_name: str,
    patients: list[str],
    flow_combos: list[str],
) -> list[dict]:
    """Build a card for scenario.started event with simulation label."""
    patient_list = ", ".join(f"`{p}`" for p in patients[:5])
    if len(patients) > 5:
        patient_list += f" (+{len(patients) - 5} more)"
    flow_list = ", ".join(flow_combos[:5])
    if len(flow_combos) > 5:
        flow_list += f" (+{len(flow_combos) - 5} more)"

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[SIMULATION] {scenario_name}", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Patients:*\n{patient_list}"},
                {"type": "mrkdwn", "text": f"*Flows:*\n{flow_list}"},
            ],
        },
    ]


def scenario_completed_card(scenario_name: str, stats: dict) -> list[dict]:
    """Build a footer card for scenario.completed with core stats."""
    stat_lines = [f"*{k}:* {v}" for k, v in stats.items()]
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"[SIMULATION COMPLETE] {scenario_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(stat_lines) if stat_lines else "_No stats_",
            },
        },
    ]
