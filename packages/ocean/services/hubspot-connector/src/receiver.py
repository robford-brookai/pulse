"""FastAPI router for HubSpot webhook ingestion."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import structlog
from fastapi import APIRouter, HTTPException, Request

from src.normalizer import normalize_event

log = structlog.get_logger()

router = APIRouter()

MAX_TIMESTAMP_AGE_SECS = 300


def _validate_hubspot_signature(
    method: str,
    url: str,
    body: bytes,
    timestamp: str,
    received_sig: str,
    secret: str,
) -> None:
    """Validate HubSpot v3 webhook signature. Raises HTTP 401 on mismatch.

    HubSpot v3 signs: client_secret + HTTP method + URL + body + timestamp.
    Also rejects requests older than 5 minutes (replay protection).
    """
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid timestamp")

    age = abs(int(time.time()) - ts)
    if age > MAX_TIMESTAMP_AGE_SECS:
        raise HTTPException(status_code=401, detail="Request timestamp too old")

    source = secret + method + url + body.decode("utf-8") + timestamp
    expected = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, received_sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/webhook")
async def receive_hubspot_webhook(request: Request) -> dict:
    """Receive a HubSpot webhook event.

    Validates v3 signature, normalizes contact lifecycle events to Ocean
    signals, and publishes to ocean.signals. HubSpot sends batches of
    subscription events in a single request.
    """
    body = await request.body()
    received_sig = request.headers.get("x-hubspot-signature-v3", "")
    timestamp = request.headers.get("x-hubspot-request-timestamp", "")
    secret = os.environ.get("HUBSPOT_CLIENT_SECRET", "")

    url = str(request.url)
    method = request.method

    _validate_hubspot_signature(method, url, body, timestamp, received_sig, secret)

    raw_events = json.loads(body)
    if not isinstance(raw_events, list):
        raw_events = [raw_events]

    publisher = request.app.state.publisher
    accepted = 0

    for raw_event in raw_events:
        log.info(
            "hubspot_event_received",
            subscription_type=raw_event.get("subscriptionType"),
            object_id=raw_event.get("objectId"),
        )

        event = normalize_event(raw_event)
        if event is None:
            continue

        await publisher.publish(
            topic="ocean.signals",
            key=event["entity_id"],
            value=json.dumps(event).encode(),
        )
        accepted += 1

    if accepted == 0:
        return {"status": "skipped"}
    return {"status": "accepted", "count": accepted}
