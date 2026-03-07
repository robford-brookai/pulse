"""FastAPI router for Impilo webhook ingestion."""
from __future__ import annotations

import hmac
import json
import os
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, HTTPException, Request

from src.normalizer import normalize_impilo_payload

log = structlog.get_logger()

router = APIRouter()


def _validate_api_key(received: str) -> None:
    """Validate Impilo API key using timing-safe comparison. Raises HTTP 401 on mismatch."""
    expected = os.environ["IMPILO_API_KEY"]
    if not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/webhooks/impilo")
async def receive_impilo_webhook(request: Request) -> dict:
    """Receive an Impilo device/patient webhook.

    Validates Impilo-API-Key header, normalises payload to a canonical OceanEvent,
    publishes to the correct Redpanda topic, and writes an audit_log row on success.
    """
    api_key = request.headers.get("Impilo-API-Key", "")
    _validate_api_key(api_key)

    body = await request.body()
    raw = json.loads(body)
    log.debug("impilo_webhook_received", event_type=raw.get("type"), keys=list(raw.keys()))

    try:
        event, topic = normalize_impilo_payload(raw)
    except ValueError as exc:
        log.warning("impilo_normalize_failed", error=str(exc), event_type=raw.get("type"))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    publisher = request.app.state.publisher
    await publisher.publish(
        topic=topic,
        key=str(event.event_id),
        value=json.dumps(event.model_dump(mode="json")).encode(),
    )

    # Audit log -- only on successful publish
    session_maker = request.app.state.session_maker
    async with session_maker() as session:
        async with session.begin():
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
                    "source_system": "impilo",
                    "entity_type": event.entity_type,
                    "entity_id": event.entity_id,
                    "timestamp": datetime.now(tz=timezone.utc),
                    "detail": json.dumps(
                        {"event_type": event.event_type, "impilo_type": raw.get("type")}
                    ),
                },
            )

    return {"status": "accepted", "event_id": str(event.event_id)}
