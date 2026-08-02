"""Slash command handlers for /ocean subcommands (status, patient, sim, ticket, help)."""

from __future__ import annotations

from datetime import UTC, datetime

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
            "query { connector_health(order_by: {connector_name: asc}) { connector_name last_seen } }"
        )
        services = health_result.get("data", {}).get("connector_health", [])
        if services:
            now = datetime.now(tz=UTC)
            health_lines = []
            for s in services:
                name = s["connector_name"]
                last_seen = datetime.fromisoformat(s["last_seen"])
                age_secs = (now - last_seen).total_seconds()
                age_min = int(age_secs / 60)
                status = "ok" if age_secs < 300 else "stale"
                health_lines.append(f"  {name}: {status} ({age_min}m ago)")
            health_lines = "\n".join(health_lines)
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
        completed_count = data.get("completed", {}).get(agg, {}).get("count", 0)

        task_text = f"*Task Counts*\n  Open: {open_count}  |  Claimed: {claimed_count}  |  Completed: {completed_count}"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": task_text},
        })

        # Last simulation from projected simulations table
        sim_result = await _hasura_query(
            """query {
                simulations(order_by: {completed_at: desc}, limit: 1) {
                    scenario_name completed_at patients_count
                }
            }"""
        )
        sims = sim_result.get("data", {}).get("simulations", [])
        if sims:
            s = sims[0]
            sim_ts = datetime.fromisoformat(s["completed_at"])
            sim_age = int((datetime.now(tz=UTC) - sim_ts).total_seconds() / 60)
            last_sim = f"{s['scenario_name']} — {s['patients_count']} patients, {sim_age}m ago"
        else:
            last_sim = "No simulations run"

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
        alert_count = alert_result.get("data", {}).get("alerts_aggregate", {}).get("aggregate", {}).get("count", 0)

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


_TIMELINE_EMOJI: dict[str, str] = {
    "alert": ":rotating_light:",
    "task": ":clipboard:",
    "ticket": ":ticket:",
    "fulfillment": ":package:",
    "return": ":leftwards_arrow_with_hook:",
    "device": ":electric_plug:",
    "interaction": ":telephone_receiver:",
    "signal": ":chart_with_upwards_trend:",
}

_TIMELINE_MAX_ENTRIES = 30


async def build_patient_response(patient_id: str) -> list[dict]:
    """Build Block Kit blocks for /ocean patient <id>.

    Queries the patient_timeline view for a consolidated timeline across
    alerts, tasks, tickets, fulfillments, returns, devices, interactions,
    and signals. Returns summary card + chronological timeline.
    No PHI -- uses patient hash and categorical fields only.
    """
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Patient: {patient_id}"},
        },
    ]

    try:
        result = await _hasura_query(
            """query GetPatientTimeline($pid: String!) {
                patients(where: {patient_id: {_eq: $pid}}) {
                    patient_id enrollment_status
                }
                patient_timeline(
                    where: {patient_id: {_eq: $pid}}
                    order_by: {created_at: desc}
                ) {
                    event_type event_id status summary created_at
                }
            }""",
            {"pid": patient_id},
        )
        patients = result.get("data", {}).get("patients", [])
        timeline = result.get("data", {}).get("patient_timeline", [])

        if not patients:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"No patient found with ID `{patient_id}`"},
            })
            return blocks

        patient = patients[0]

        # Compute summary counts from timeline rows
        open_alerts = sum(1 for e in timeline if e.get("event_type") == "alert" and e.get("status") == "open")
        active_tasks = sum(
            1 for e in timeline if e.get("event_type") == "task" and e.get("status") in ("open", "claimed")
        )
        open_tickets = sum(
            1
            for e in timeline
            if e.get("event_type") == "ticket" and e.get("status") in ("open", "in_progress", "waiting")
        )
        active_devices = sum(1 for e in timeline if e.get("event_type") == "device" and e.get("status") == "associated")
        pending_fulfillments = sum(
            1
            for e in timeline
            if e.get("event_type") == "fulfillment" and e.get("status") not in ("delivered", "cancelled")
        )

        # Last RMA
        rma_entries = [e for e in timeline if e.get("event_type") == "return"]
        last_rma = rma_entries[0].get("summary", "None") if rma_entries else "None"

        # Last interaction
        interaction_entries = [e for e in timeline if e.get("event_type") == "interaction"]
        last_interaction_text = ""
        if interaction_entries:
            li = interaction_entries[0]
            last_interaction_text = f"*Last Interaction:* {li.get('summary', 'n/a')} at {li.get('created_at', '')}"

        summary_lines = [
            f"*Status:* {patient.get('enrollment_status', 'unknown')}",
            f"*Open Alerts:* {open_alerts}",
            f"*Active Tasks:* {active_tasks}",
            f"*Open Tickets:* {open_tickets}",
            f"*Active Devices:* {active_devices}",
            f"*Pending Fulfillments:* {pending_fulfillments}",
            f"*Last RMA:* {last_rma}",
        ]
        if last_interaction_text:
            summary_lines.append(last_interaction_text)

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)},
        })

        # Timeline section with emoji prefixes
        total_events = len(timeline)
        display_entries = timeline[:_TIMELINE_MAX_ENTRIES]

        if display_entries:
            timeline_lines = []
            if total_events > _TIMELINE_MAX_ENTRIES:
                timeline_lines.append(
                    f"_Showing {_TIMELINE_MAX_ENTRIES} of {total_events} events. Use GraphQL for full history._"
                )
            for entry in display_entries:
                etype = entry.get("event_type", "")
                emoji = _TIMELINE_EMOJI.get(etype, ":grey_question:")
                ts = entry.get("created_at", "")
                summary = entry.get("summary", "")
                timeline_lines.append(f"  {emoji} {ts}: {summary}")

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Timeline*\n" + "\n".join(timeline_lines),
                },
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
                    "text": (f"Simulation triggered: *{scenario}*\nCheck #care-alerts-ops for progress."),
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


async def build_search_response(query: str) -> list[dict]:
    """Build Block Kit blocks for /ocean search <query>.

    Calls stacte-bridge's /search endpoint and formats top-k results
    as Block Kit section blocks showing entity info and similarity score.
    """
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Search: {query}"},
        },
    ]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "http://stacte-bridge:8000/search",
                params={"q": query, "entity_type": "alerts", "top_k": 10},
                timeout=10.0,
            )
            resp.raise_for_status()
            results = resp.json()

        if not results:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No results found."},
            })
            return blocks

        for i, result in enumerate(results, 1):
            entity_id = result.get("entity_id", "unknown")
            distance = result.get("distance", 0.0)
            score = 1.0 - distance if distance <= 1.0 else distance
            entity_type = result.get("entity_type", "alert")
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (f"*{i}.* `{entity_id}`\n  Type: {entity_type}  |  Score: {score:.3f}"),
                },
            })

    except Exception as exc:
        log.error("slash_search_error", error=str(exc), query=query)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Error searching: {exc}",
            },
        })

    return blocks


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
                    "  `/ocean patient <id>` -- Patient summary card with consolidated timeline\n"
                    "  `/ocean sim <scenario>` -- Trigger a simulation run\n"
                    "  `/ocean search <query>` -- Semantic search across alerts\n"
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
    elif subcommand == "search":
        if not arg:
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Usage: `/ocean search <query>`"},
                },
            ]
        else:
            blocks = await build_search_response(arg)
    else:
        # help or unknown subcommand
        blocks = build_help_response()

    await respond(blocks=blocks)
