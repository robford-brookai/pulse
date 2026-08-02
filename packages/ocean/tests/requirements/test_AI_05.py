"""AI-05: All four AI audit events are published correctly.

Requirement: The system publishes canonical audit events to ocean.ai-ops for
each AI action:
  - ai.summary.generated  (after Claude generates a summary)
  - ai.response.drafted   (after draft is persisted)
  - ai.output.approved    (after coordinator approves)
  - ai.output.rejected    (after coordinator rejects)

Each event must include the canonical envelope fields: event_id, event_type,
timestamp, source_system, entity_type, entity_id, payload.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from utils import setup_service

setup_service("slack-bot")

from src.ai_events import publish_ai_event

_ALL_EVENT_TYPES = [
    "ai.summary.generated",
    "ai.response.drafted",
    "ai.output.approved",
    "ai.output.rejected",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", _ALL_EVENT_TYPES)
async def test_publish_ai_event_publishes_to_ocean_ai_ops(event_type: str):
    """publish_ai_event sends to the 'ocean.ai-ops' topic for each event type."""
    mock_publisher = AsyncMock()
    mock_publisher.publish = AsyncMock(return_value=None)

    await publish_ai_event(
        publisher=mock_publisher,
        event_type=event_type,
        task_id="task-abc",
        patient_id="patient-raw-id",
        payload={"draft_id": "draft-001", "actor_id": "U_ACTOR"},
    )

    mock_publisher.publish.assert_awaited_once()
    call_args = mock_publisher.publish.call_args
    topic = call_args.args[0]
    assert topic == "ocean.ai-ops", f"Expected 'ocean.ai-ops', got '{topic}'"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", _ALL_EVENT_TYPES)
async def test_publish_ai_event_envelope_structure(event_type: str):
    """Published event contains all required canonical envelope fields."""
    mock_publisher = AsyncMock()
    captured: list[dict] = []

    async def capture(topic, event):
        captured.append(event)

    mock_publisher.publish = capture

    await publish_ai_event(
        publisher=mock_publisher,
        event_type=event_type,
        task_id="task-xyz",
        patient_id="patient-xyz",
        payload={"draft_id": "draft-002"},
    )

    assert len(captured) == 1
    event = captured[0]
    for field in ("event_id", "event_type", "timestamp", "source_system", "entity_type", "entity_id", "payload"):
        assert field in event, f"Canonical field '{field}' missing from event envelope"

    assert event["event_type"] == event_type
    assert event["entity_id"] == "task-xyz"
    assert event["source_system"] == "ocean"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", _ALL_EVENT_TYPES)
async def test_publish_ai_event_hashes_patient_id(event_type: str):
    """Raw patient_id is never written to event stream — only its sha256 hash."""
    import hashlib

    mock_publisher = AsyncMock()
    captured: list[dict] = []

    async def capture(topic, event):
        captured.append(event)

    mock_publisher.publish = capture

    raw_patient_id = "patient-raw-id-123"
    expected_hash = hashlib.sha256(raw_patient_id.encode()).hexdigest()

    await publish_ai_event(
        publisher=mock_publisher,
        event_type=event_type,
        task_id="task-xyz",
        patient_id=raw_patient_id,
        payload={},
    )

    event = captured[0]
    payload = event["payload"]
    assert payload.get("patient_id_hash") == expected_hash
    # Raw ID must NOT appear anywhere in the event
    event_str = str(event)
    assert raw_patient_id not in event_str, "Raw patient_id leaked into event stream"


@pytest.mark.asyncio
async def test_publish_ai_event_does_not_reraise_on_publisher_failure():
    """Audit failure must not break user flow — exceptions are swallowed."""
    mock_publisher = AsyncMock()
    mock_publisher.publish = AsyncMock(side_effect=RuntimeError("Kafka down"))

    # Should not raise
    await publish_ai_event(
        publisher=mock_publisher,
        event_type="ai.output.approved",
        task_id="task-xyz",
        patient_id="pt",
        payload={},
    )
