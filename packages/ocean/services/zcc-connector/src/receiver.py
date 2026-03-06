"""FastAPI router for ZCC (Zoom Contact Center) webhook ingestion."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request

from src.normalizer import normalize_zcc_event

log = structlog.get_logger()

router = APIRouter()


def _validate_zoom_signature(body: bytes, timestamp: str, received_sig: str, secret: str) -> None:
    """Validate Zoom v0 HMAC-SHA256 webhook signature. Raises HTTP 401 on mismatch.

    Zoom signature format:
      message  = "v0:{timestamp}:{raw_body_string}"
      expected = "v0=" + HMAC-SHA256(secret, message).hexdigest()
      header   = x-zm-signature
    """
    message = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/webhooks/zcc")
async def receive_zcc_webhook(request: Request) -> dict:
    """Receive a Zoom Contact Center webhook.

    Validates Zoom v0 HMAC-SHA256 signature, handles url_validation challenge,
    normalizes known events to Ocean canonical format, and publishes to
    ocean.interactions. Unknown events are logged and silently skipped.
    Always returns HTTP 200 on success (or 401 on signature failure).
    """
    # CRITICAL: read raw bytes FIRST — HMAC is computed on wire bytes before JSON parsing
    body = await request.body()

    timestamp = request.headers.get("x-zm-request-timestamp", "")
    received_sig = request.headers.get("x-zm-signature", "")

    secret = os.environ["ZCC_WEBHOOK_SECRET"]
    _validate_zoom_signature(body, timestamp, received_sig, secret)

    raw = json.loads(body)

    # Handle Zoom url_validation challenge (Pitfall 5 mitigation) — BEFORE normalization
    if raw.get("event") == "endpoint.url_validation":
        plain_token = raw.get("payload", {}).get("plainToken", "")
        encrypted = hmac.new(secret.encode(), plain_token.encode(), hashlib.sha256).hexdigest()
        return {"plainToken": plain_token, "encryptedToken": encrypted}

    # Log raw event name at INFO level BEFORE normalization (Pitfall 1 mitigation)
    # This ensures actual ZCC event names are captured in logs even if mapping is wrong.
    log.info("zcc_event_received", zcc_event=raw.get("event", ""))

    ocean_event = normalize_zcc_event(raw)
    if ocean_event is None:
        log.info("zcc_event_skipped", zcc_event=raw.get("event", ""), reason="no_mapping")
        return {"status": "ok"}

    publisher = request.app.state.publisher
    await publisher.publish(
        topic="ocean.interactions",
        key=ocean_event["entity_id"] or str(uuid.uuid4()),
        value=json.dumps(ocean_event).encode(),
    )

    return {"status": "accepted"}
