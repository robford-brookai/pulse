"""Slash command handlers for /ocean subcommands (status, patient, sim, ticket, help)."""
from __future__ import annotations

import json

import httpx
import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level injectable dependencies (set by main.py during lifespan)
# ---------------------------------------------------------------------------

_hasura_url: str = ""
_hasura_secret: str = ""


def set_slash_deps(hasura_url: str, hasura_secret: str) -> None:
    """Wire Hasura connection info for slash command handlers."""
    global _hasura_url, _hasura_secret
    _hasura_url = hasura_url
    _hasura_secret = hasura_secret


# ---------------------------------------------------------------------------
# Hasura GraphQL helper
# ---------------------------------------------------------------------------


async def _hasura_query(query: str, variables: dict | None = None) -> dict:
    """Execute a Hasura GraphQL query and return the JSON result."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_hasura_url}/v1/graphql",
            json={"query": query, "variables": variables or {}},
            headers={"x-hasura-admin-secret": _hasura_secret},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


async def build_status_response() -> list[dict]:
    """Build Block Kit blocks for /ocean status.

    Queries Hasura for service health, task counts, last sim timestamp,
    and active alert count.
    """
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Ocean Status"},
        },
    ]

    try:
        # Service health from connector_health table
        health_result = await _hasura_query(
            "query { connector_health { name status } }"
        )
        services = health_result.get("data", {}).get("connector_health", [])
        if services:
            health_lines = "\n".join(
                f"  {s['name']}: {s['status']}" for s in services
            )
        else:
            health_lines = "  No services reporting"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Service Health*\n{health_lines}"},
        })

        # Task counts by status
        task_result = await _hasura_query(
            """query {
                open: tasks_aggregate(
                    where: {status: {_eq: "open"}}
                ) { aggregate { count } }
                claimed: tasks_aggregate(
                    where: {status: {_eq: "claimed"}}
                ) { aggregate { count } }
                completed: tasks_aggregate(
                    where: {status: {_eq: "completed"}}
                ) { aggregate { count } }
            }"""
        )
        data = task_result.get("data", {})
        agg = "aggregate"
        open_count = data.get("open", {}).get(agg, {}).get("count", 0)
        claimed_count = data.get("claimed", {}).get(agg, {}).get("count", 0)
        completed_count = (
            data.get("completed", {}).get(agg, {}).get("count", 0)
        )

        task_text = (
            f"*Task Counts*\n"
            f"  Open: {open_count}  |  "
            f"Claimed: {claimed_count}  |  "
            f"Completed: {completed_count}"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": task_text},
        })

        # Last simulation timestamp
        sim_result = await _hasura_query(
            """query {
                events(
                    where: {event_type: {_eq: "scenario.completed"}}
                    order_by: {timestamp: desc}
                    limit: 1
                ) { timestamp }
            }"""
        )
        sim_events = sim_result.get("data", {}).get("events", [])
        last_sim = sim_events[0]["timestamp"] if sim_events else "No simulations run"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Last Simulation*\n  {last_sim}"},
        })

        # Active alerts count
        alert_result = await _hasura_query(
            """query {
                alerts_aggregate(where: {status: {_eq: "open"}}) {
                    aggregate { count }
                }
            }"""
        )
        alert_count = (
            alert_result.get("data", {})
            .get("alerts_aggregate", {})
            .get("aggregate", {})
            .get("count", 0)
        )

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Active Alerts*\n  {alert_count}"},
        })

    except Exception as exc:
        log.error("slash_status_error", error=str(exc))
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"Error fetching status: {exc}"},
        })

    return blocks


async def build_patient_response(patient_id: str) -> list[dict]:
    """Build Block Kit blocks for /ocean patient <id>.

    Queries Hasura for patient signals, alerts, tasks, and interactions.
    Returns summary card + chronological timeline. No PHI -- uses patient
    hash and categorical fields only.
    """
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Patient: {patient_id}"},
        },
    ]

    try:
        result = await _hasura_query(
            """query GetPatient($pid: String!) {
                patients(where: {patient_id: {_eq: $pid}}) {
                    patient_id status
                    signals(order_by: {created_at: desc}, limit: 10) {
                        type value created_at
                    }
                    alerts(where: {status: {_eq: "open"}}, order_by: {created_at: desc}) {
                        id severity status created_at
                    }
                    tasks(order_by: {created_at: desc}, limit: 10) {
                        id status priority type
                    }
                    interactions(order_by: {created_at: desc}, limit: 1) {
                        id type outcome created_at
                    }
                }
            }""",
            {"pid": patient_id},
        )
        patients = result.get("data", {}).get("patients", [])

        if not patients:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"No patient found with ID `{patient_id}`"},
            })
            return blocks

        patient = patients[0]

        # Summary section
        open_alerts = patient.get("alerts", [])
        active_tasks = [
            t for t in patient.get("tasks", [])
            if t.get("status") in ("open", "claimed")
        ]
        last_interaction = patient.get("interactions", [])

        summary_lines = [
            f"*Status:* {patient.get('status', 'unknown')}",
            f"*Open Alerts:* {len(open_alerts)}",
            f"*Active Tasks:* {len(active_tasks)}",
        ]
        if last_interaction:
            li = last_interaction[0]
            li_type = li.get("type", "unknown")
            li_outcome = li.get("outcome", "n/a")
            li_time = li.get("created_at", "")
            summary_lines.append(
                f"*Last Interaction:* {li_type}"
                f" ({li_outcome}) at {li_time}"
            )

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)},
        })

        # Timeline -- merge signals, alerts, tasks by timestamp
        timeline_items = []
        for sig in patient.get("signals", []):
            ts = sig.get("created_at", "")
            desc = f"Signal: {sig.get('type')} = {sig.get('value')}"
            timeline_items.append((ts, desc))
        for alert in open_alerts:
            ts = alert.get("created_at", "")
            sev = alert.get("severity")
            desc = f"Alert: {sev} ({alert.get('status')})"
            timeline_items.append((ts, desc))
        for task in patient.get("tasks", []):
            tid = task.get("id", "")
            desc = f"Task: {task.get('type')} [{task.get('status')}]"
            timeline_items.append((tid, desc))

        timeline_items.sort(key=lambda x: x[0], reverse=True)

        if timeline_items:
            timeline_text = "\n".join(
                f"  {ts}: {desc}"
                for ts, desc in timeline_items[:10]
            )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Timeline*\n{timeline_text}"},
            })

    except Exception as exc:
        log.error("slash_patient_error", error=str(exc), patient_id=patient_id)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"Error fetching patient data: {exc}"},
        })

    return blocks


async def trigger_sim_response(scenario: str) -> list[dict]:
    """Trigger a simulation run via sim-driver and return confirmation blocks."""
    try:
        sim_url = "http://sim-driver:8060"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{sim_url}/simulate",
                json={"scenario": scenario},
                timeout=30.0,
            )
            resp.raise_for_status()

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Simulation triggered: *{scenario}*\n"
                        "Check #care-alerts-ops for progress."
                    ),
                },
            },
        ]
    except Exception as exc:
        log.error("slash_sim_error", error=str(exc), scenario=scenario)
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Error triggering simulation `{scenario}`: {exc}",
                },
            },
        ]


CATEGORY_CHANNEL_MAP: dict[str, str] = {
    "device_issue": "#ocean-devices",
    "patient_activation": "#ocean-activation",
    "clinical_support": "#ocean-clinical",
    "engineering_it": "#ocean-engineering",
}


def build_ticket_modal(private_metadata: str = "", prefill_description: str = "") -> dict:
    """Build the Slack modal view JSON for ticket creation.

    Args:
        private_metadata: JSON string with source_message_url etc.
        prefill_description: Pre-filled description text (from message action).
    """
    description_element: dict = {
        "type": "plain_text_input",
        "action_id": "description_input",
        "multiline": True,
        "placeholder": {"type": "plain_text", "text": "Describe the issue..."},
    }
    if prefill_description:
        description_element["initial_value"] = prefill_description

    return {
        "type": "modal",
        "callback_id": "ticket_create_modal",
        "title": {"type": "plain_text", "text": "Create Ticket"},
        "submit": {"type": "plain_text", "text": "Create"},
        "private_metadata": private_metadata,
        "blocks": [
            {
                "type": "input",
                "block_id": "category_block",
                "element": {
                    "type": "static_select",
                    "action_id": "category_select",
                    "placeholder": {"type": "plain_text", "text": "Select category"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Device Issue"}, "value": "device_issue"},
                        {"text": {"type": "plain_text", "text": "Patient Activation"}, "value": "patient_activation"},
                        {"text": {"type": "plain_text", "text": "Clinical Support"}, "value": "clinical_support"},
                        {"text": {"type": "plain_text", "text": "Engineering / IT"}, "value": "engineering_it"},
                    ],
                },
                "label": {"type": "plain_text", "text": "Category"},
            },
            {
                "type": "input",
                "block_id": "description_block",
                "element": description_element,
                "label": {"type": "plain_text", "text": "Description"},
            },
            {
                "type": "input",
                "block_id": "priority_block",
                "element": {
                    "type": "static_select",
                    "action_id": "priority_select",
                    "placeholder": {"type": "plain_text", "text": "Select priority"},
                    "initial_option": {"text": {"type": "plain_text", "text": "Medium"}, "value": "medium"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Critical"}, "value": "critical"},
                        {"text": {"type": "plain_text", "text": "High"}, "value": "high"},
                        {"text": {"type": "plain_text", "text": "Medium"}, "value": "medium"},
                        {"text": {"type": "plain_text", "text": "Low"}, "value": "low"},
                    ],
                },
                "label": {"type": "plain_text", "text": "Priority"},
            },
            {
                "type": "input",
                "block_id": "patient_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "patient_input",
                    "placeholder": {"type": "plain_text", "text": "Patient ID (optional)"},
                },
                "label": {"type": "plain_text", "text": "Patient ID"},
            },
            {
                "type": "input",
                "block_id": "related_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "related_input",
                    "placeholder": {"type": "plain_text", "text": "e.g. DEV-00041"},
                },
                "label": {"type": "plain_text", "text": "Related Ticket"},
            },
        ],
    }


def build_help_response() -> list[dict]:
    """Build Block Kit blocks listing all /ocean subcommands."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Ocean Commands"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Available commands:*\n"
                    "  `/ocean status` -- Service health, task counts,"
                    " last sim, active alerts\n"
                    "  `/ocean patient <id>` -- Patient summary card with timeline\n"
                    "  `/ocean sim <scenario>` -- Trigger a simulation run\n"
                    "  `/ocean ticket` -- Create a new ticket (opens modal)\n"
                    "  `/ocean help` -- Show this help message"
                ),
            },
        },
    ]


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


async def handle_ocean_command(ack, body, respond, client=None) -> None:
    """/ocean slash command router.

    Must ack() first (Slack 3-second timeout), then parse subcommand
    and dispatch to the appropriate builder. The `client` kwarg is
    injected by Bolt and required for the `ticket` subcommand (modal).
    """
    await ack()

    text = (body.get("text") or "").strip()
    parts = text.split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    log.info("ocean_command", subcommand=subcommand, arg=arg)

    if subcommand == "ticket":
        if client is None:
            log.error("ticket_subcommand_requires_client")
            return
        await client.views_open(
            trigger_id=body["trigger_id"],
            view=build_ticket_modal(),
        )
        return

    if subcommand == "status":
        blocks = await build_status_response()
    elif subcommand == "patient":
        if not arg:
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Usage: `/ocean patient <patient_id>`"},
                },
            ]
        else:
            blocks = await build_patient_response(arg)
    elif subcommand == "sim":
        if not arg:
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Usage: `/ocean sim <scenario>`"},
                },
            ]
        else:
            blocks = await trigger_sim_response(arg)
    else:
        # help or unknown subcommand
        blocks = build_help_response()

    await respond(blocks=blocks)
