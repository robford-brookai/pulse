"""FastAPI router for POCAR webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, HTTPException, Request

from src.normalizer import normalize_pocar_payload

log = structlog.get_logger()

router = APIRouter()


def _validate_signature(body: bytes, received: str) -> None:
    """Validate HMAC-SHA256 webhook signature. Raises HTTP 401 on mismatch."""
    secret = os.environ["POCAR_WEBHOOK_SECRET"]
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/webhooks/pocar")
async def receive_pocar_webhook(request: Request) -> dict:
    """Receive a POCAR care alert webhook.

    Validates HMAC-SHA256 signature, normalises payload to a canonical OceanEvent,
    publishes to the ``alerts`` domain, and writes an audit_log row on success.
    Always returns HTTP 200 to POCAR — the publisher's DLQ handles bus failures silently.
    """
    # CRITICAL: read raw bytes FIRST (HMAC computed on wire bytes, before JSON parsing)
    body = await request.body()

    sig_header = request.headers.get("X-Pocar-Signature", "")
    _validate_signature(body, sig_header)

    raw = json.loads(body)
    log.debug("pocar_webhook_received", keys=list(raw.keys()))

    event = normalize_pocar_payload(raw)

    publisher = request.app.state.publisher
    # The envelope crosses the bus whole, as a dict: the publisher owns serialisation, and
    # `alerts` is the domain, not the envelope's own event_type.
    await publisher.publish(
        detail_type="alerts",
        event=event.model_dump(mode="json"),
        key=str(event.event_id),
    )

    # Write audit_log row — the publish never raises, so a DLQ'd event is still audited as
    # received, which is what the row records.
    session_maker = request.app.state.session_maker
    async with session_maker() as session, session.begin():
        await session.execute(
            sa.text(
                "INSERT INTO audit_log "
                "(audit_id, event_id, action_type, actor_id, source_system, "
                "entity_type, entity_id, timestamp, detail) "
                "VALUES "
                "(:audit_id, :event_id, :action_type, :actor_id, :source_system, "
                ":entity_type, :entity_id, :timestamp, :detail)"
            ),
            {
                "audit_id": str(uuid.uuid4()),
                "event_id": str(event.event_id),
                "action_type": "webhook_received",
                "actor_id": "system",
                "source_system": "pocar",
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "timestamp": datetime.now(tz=UTC),
                "detail": json.dumps({"event_type": event.event_type}),
            },
        )

    return {"status": "accepted", "event_id": str(event.event_id)}
