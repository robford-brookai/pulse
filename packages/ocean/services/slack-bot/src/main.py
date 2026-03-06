# AUDIT-04 GATE: Anthropic HIPAA BAA must be confirmed before deploying to production.
# This service is safe to build and test locally. Production deploy is blocked until BAA is in place.
# Track BAA status: [link to Linear/Notion issue]
"""slack-bot FastAPI app — health endpoint and Slack bolt integration."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response

log = structlog.get_logger()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("slack_bot_starting")
    yield
    log.info("slack_bot_stopped")


app = FastAPI(title="slack-bot", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "slack-bot", "version": "0.1.0"}
