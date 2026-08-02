"""FastAPI router for Linear webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import structlog
from fastapi import APIRouter, HTTPException, Request

from src.normalizer import normalize_issue

log = structlog.get_logger()

router = APIRouter()


def _validate_linear_signature(body: bytes, received_sig: str, secret: str) -> None:
    """Validate Linear webhook HMAC-SHA256 signature. Raises HTTP 401 on mismatch.

    Linear sends the signature in the `linear-signature` header as
    HMAC-SHA256(webhook_secret, raw_body).hex().
    """
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/webhook")
async def receive_linear_webhook(request: Request) -> dict:
    """Receive a Linear webhook event.

    Validates signature, checks for 'ocean' label, normalizes to Ocean
    ticket event, and publishes to ocean.tickets. Issues without the
    'ocean' label are silently skipped (200 with status=skipped).
    """
    body = await request.body()
    received_sig = request.headers.get("linear-signature", "")
    secret = os.environ.get("LINEAR_WEBHOOK_SECRET", "")

    _validate_linear_signature(body, received_sig, secret)

    raw = json.loads(body)
    action = raw.get("action", "")
    issue_data = raw.get("data", {})
    labels = issue_data.get("labels", [])

    log.info("linear_event_received", action=action, issue_id=issue_data.get("id"))

    # Check for "ocean" label (case-insensitive)
    has_ocean_label = any(label.get("name", "").lower() == "ocean" for label in labels)
    if not has_ocean_label:
        log.info("linear_event_skipped", reason="no ocean label")
        return {"status": "skipped", "reason": "no ocean label"}

    event = normalize_issue(issue_data, action)
    if event is None:
        log.info("linear_event_skipped", reason="unsupported action", action=action)
        return {"status": "skipped"}

    publisher = request.app.state.publisher
    await publisher.publish("ocean.tickets", event)

    return {"status": "accepted"}
