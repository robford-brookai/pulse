"""MCP server — 12 operational tools for Ocean Slack Connector."""

from __future__ import annotations

import os

import httpx
import structlog
from fastmcp import FastMCP

log = structlog.get_logger()

mcp = FastMCP("Ocean Slack Connector")

# ---------------------------------------------------------------------------
# Dependency holders (same pattern as bolt_app.py)
# ---------------------------------------------------------------------------
_slack_client = None
_session_maker = None
_publisher = None
_hasura_url: str = ""
_hasura_secret: str = ""


def set_mcp_deps(
    slack_client,
    session_maker,
    publisher,
    hasura_url: str,
    hasura_secret: str,
):
    """Wire runtime dependencies into MCP tool scope."""
    global _slack_client, _session_maker, _publisher, _hasura_url, _hasura_secret
    _slack_client = slack_client
    _session_maker = session_maker
    _publisher = publisher
    _hasura_url = hasura_url
    _hasura_secret = hasura_secret


def create_mcp_app():
    """Return the ASGI app to mount at /mcp."""
    return mcp.http_app(path="/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _hasura_query(query: str, variables: dict | None = None) -> dict:
    """Execute a Hasura GraphQL query."""
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
# Slack tools (6)
# ---------------------------------------------------------------------------


@mcp.tool()
async def slack_send_message(channel: str, text: str) -> dict:
    """Post a message to a Slack channel."""
    log.info("mcp_tool_call", tool="slack_send_message", channel=channel)
    try:
        resp = await _slack_client.chat_postMessage(channel=channel, text=text)
        return {"ok": True, "ts": resp["ts"]}
    except Exception as e:
        log.error("mcp_tool_error", tool="slack_send_message", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def slack_post_card(channel: str, blocks: list[dict], text: str) -> dict:
    """Post a Block Kit card to a Slack channel."""
    log.info("mcp_tool_call", tool="slack_post_card", channel=channel)
    try:
        resp = await _slack_client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=text,
        )
        return {"ok": True, "ts": resp["ts"]}
    except Exception as e:
        log.error("mcp_tool_error", tool="slack_post_card", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def slack_read_channel(channel: str, limit: int = 20) -> dict:
    """Read recent messages from a Slack channel."""
    log.info("mcp_tool_call", tool="slack_read_channel", channel=channel, limit=limit)
    try:
        resp = await _slack_client.conversations_history(channel=channel, limit=limit)
        return {"messages": resp.get("messages", [])}
    except Exception as e:
        log.error("mcp_tool_error", tool="slack_read_channel", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def slack_react(channel: str, timestamp: str, emoji: str) -> dict:
    """Add an emoji reaction to a Slack message."""
    log.info("mcp_tool_call", tool="slack_react", channel=channel, emoji=emoji)
    try:
        await _slack_client.reactions_add(channel=channel, timestamp=timestamp, name=emoji)
        return {"ok": True}
    except Exception as e:
        log.error("mcp_tool_error", tool="slack_react", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def slack_update_message(
    channel: str,
    timestamp: str,
    text: str,
    blocks: list[dict] | None = None,
) -> dict:
    """Update an existing Slack message."""
    log.info("mcp_tool_call", tool="slack_update_message", channel=channel, ts=timestamp)
    try:
        kwargs: dict = {"channel": channel, "ts": timestamp, "text": text}
        if blocks is not None:
            kwargs["blocks"] = blocks
        await _slack_client.chat_update(**kwargs)
        return {"ok": True}
    except Exception as e:
        log.error("mcp_tool_error", tool="slack_update_message", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def slack_list_channels(limit: int = 100) -> dict:
    """List Slack channels the bot is a member of."""
    log.info("mcp_tool_call", tool="slack_list_channels", limit=limit)
    try:
        resp = await _slack_client.conversations_list(limit=limit)
        return {"channels": resp.get("channels", [])}
    except Exception as e:
        log.error("mcp_tool_error", tool="slack_list_channels", error=str(e))
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Ocean tools (4)
# ---------------------------------------------------------------------------


@mcp.tool()
async def ocean_get_task_status(task_id: str) -> dict:
    """Query Hasura for a task's status, patient, and alerts."""
    log.info("mcp_tool_call", tool="ocean_get_task_status", task_id=task_id)
    try:
        result = await _hasura_query(
            """
            query GetTask($id: uuid!) {
              tasks_by_pk(id: $id) {
                id status priority patient_id type
                created_at updated_at claimed_by
                alerts { id severity status created_at }
              }
            }
            """,
            {"id": task_id},
        )
        return result.get("data", {}).get("tasks_by_pk") or {"error": "task not found"}
    except Exception as e:
        log.error("mcp_tool_error", tool="ocean_get_task_status", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def ocean_get_patient_summary(patient_id: str) -> dict:
    """Query Hasura for patient signals, alerts, tasks, and interactions."""
    log.info("mcp_tool_call", tool="ocean_get_patient_summary", patient_id=patient_id)
    try:
        result = await _hasura_query(
            """
            query GetPatient($pid: String!) {
              patients(where: {patient_id: {_eq: $pid}}) {
                patient_id status
                signals(order_by: {created_at: desc}, limit: 10) { type value created_at }
                alerts(order_by: {created_at: desc}, limit: 10) { id severity status created_at }
                tasks(order_by: {created_at: desc}, limit: 10) { id status priority type }
                interactions(order_by: {created_at: desc}, limit: 5) { id type outcome created_at }
              }
            }
            """,
            {"pid": patient_id},
        )
        patients = result.get("data", {}).get("patients", [])
        return patients[0] if patients else {"error": "patient not found"}
    except Exception as e:
        log.error("mcp_tool_error", tool="ocean_get_patient_summary", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def ocean_list_open_tasks(limit: int = 50) -> dict:
    """Query Hasura for open and claimed tasks."""
    log.info("mcp_tool_call", tool="ocean_list_open_tasks", limit=limit)
    try:
        result = await _hasura_query(
            """
            query OpenTasks($limit: Int!) {
              tasks(
                where: {status: {_in: ["open", "claimed"]}}
                order_by: {created_at: desc}
                limit: $limit
              ) { id status priority patient_id type created_at claimed_by }
            }
            """,
            {"limit": limit},
        )
        return {"tasks": result.get("data", {}).get("tasks", [])}
    except Exception as e:
        log.error("mcp_tool_error", tool="ocean_list_open_tasks", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def ocean_event_replay(event_id: str) -> dict:
    """Fetch an event from event-store and re-publish to its original topic."""
    log.info("mcp_tool_call", tool="ocean_event_replay", event_id=event_id)
    try:
        event_store_url = os.environ.get("EVENT_STORE_URL", "http://localhost:8001")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{event_store_url}/events/{event_id}", timeout=10.0)
            resp.raise_for_status()
            event = resp.json()

        topic = event.get("topic", "")
        if topic and _publisher:
            await _publisher.publish(topic, event)

        return {"replayed": True, "event_type": event.get("event_type", "unknown")}
    except Exception as e:
        log.error("mcp_tool_error", tool="ocean_event_replay", error=str(e))
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Sim tools (2)
# ---------------------------------------------------------------------------

SERVICE_PORTS = {
    "event-store": 8001,
    "pocar-connector": 8002,
    "graph-projection": 8003,
    "control-plane": 8004,
    "slack-bot": 8005,
    "zcc-connector": 8006,
    "impilo-connector": 8007,
    "sim-driver": 8060,
    "agent-worker": 8061,
    "call-simulator": 8062,
    "stacte-bridge": 8070,
}


@mcp.tool()
async def sim_trigger(scenario: str = "pilot_demo", compression_ratio: float = 10.0) -> dict:
    """Trigger a simulation scenario via sim-driver."""
    log.info("mcp_tool_call", tool="sim_trigger", scenario=scenario, ratio=compression_ratio)
    try:
        sim_url = os.environ.get("SIM_DRIVER_URL", "http://sim-driver:8060")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{sim_url}/simulate",
                json={"scenario": scenario, "compression_ratio": compression_ratio},
                timeout=30.0,
            )
            resp.raise_for_status()
        return {"started": True, "scenario": scenario}
    except Exception as e:
        log.error("mcp_tool_error", tool="sim_trigger", error=str(e))
        return {"error": str(e)}


@mcp.tool()
async def ocean_service_health() -> dict:
    """Check health of all Ocean services."""
    log.info("mcp_tool_call", tool="ocean_service_health")
    results = []
    async with httpx.AsyncClient() as client:
        for name, port in SERVICE_PORTS.items():
            try:
                await client.get(f"http://localhost:{port}/health", timeout=3.0)
                results.append({"name": name, "status": "healthy", "port": port})
            except Exception:
                results.append({"name": name, "status": "unreachable", "port": port})
    return {"services": results}
