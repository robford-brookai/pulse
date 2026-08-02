"""FastAPI router for GitHub webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import structlog
from fastapi import APIRouter, HTTPException, Request

from src.normalizer import normalize_event

log = structlog.get_logger()

router = APIRouter()


def _validate_github_signature(body: bytes, received_sig: str, secret: str) -> None:
    """Validate GitHub webhook HMAC-SHA256 signature. Raises HTTP 401 on mismatch.

    GitHub sends X-Hub-Signature-256 as ``sha256=<hex>``.
    """
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/webhook")
async def receive_github_webhook(request: Request) -> dict:
    """Receive a GitHub webhook event.

    Validates signature, normalizes PR and push events to Ocean signals,
    and publishes to ocean.signals. Unsupported events return 200 with
    status=skipped.
    """
    body = await request.body()
    received_sig = request.headers.get("x-hub-signature-256", "")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    _validate_github_signature(body, received_sig, secret)

    raw = json.loads(body)
    gh_event = request.headers.get("x-github-event", "")

    log.info("github_event_received", gh_event=gh_event, action=raw.get("action"))

    event = normalize_event(raw, gh_event)
    if event is None:
        log.info("github_event_skipped", reason="unsupported event", gh_event=gh_event)
        return {"status": "skipped"}

    publisher = request.app.state.publisher
    await publisher.publish(
        topic="ocean.signals",
        key=event["entity_id"],
        value=json.dumps(event).encode(),
    )

    return {"status": "accepted"}
