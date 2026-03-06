"""Slack bolt app — stub. Full implementation in 03-03."""
from __future__ import annotations

import os

import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

log = structlog.get_logger()

bolt_app = AsyncApp(
    token=os.environ.get("SLACK_BOT_TOKEN", ""),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
)
bolt_handler = AsyncSlackRequestHandler(bolt_app)


@bolt_app.action("task_claim")
async def handle_task_claim(ack, body, client):
    """Handle task claim button action. Stub — implemented in 03-04."""
    await ack()
    log.debug("task_claim_stub", action_id="task_claim")


@bolt_app.action("task_resolve")
async def handle_task_resolve(ack, body, client):
    """Handle task resolve button action. Stub — implemented in 03-04."""
    await ack()
    log.debug("task_resolve_stub", action_id="task_resolve")
