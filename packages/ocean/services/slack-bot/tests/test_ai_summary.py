"""Tests for ai_summary and ai_events modules — Phase 4 AI assist."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# fetch_patient_context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_patient_context_returns_empty_on_failure():
    """On any httpx exception, fetch_patient_context returns {} without raising."""
    import httpx

    with patch("src.ai_summary.httpx") as mock_httpx:
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(side_effect=httpx.ConnectError("unreachable"))
        mock_httpx.AsyncClient.return_value = mock_client_instance
        mock_httpx.ConnectError = httpx.ConnectError

        from src.ai_summary import fetch_patient_context
        result = await fetch_patient_context(
            patient_id="patient-123",
            hasura_url="http://localhost:8080",
            hasura_secret="secret",
        )

    assert result == {}


# ---------------------------------------------------------------------------
# generate_summary_with_context — with signals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_summary_with_context_cites_signals():
    """When context contains signals, cited_signals includes the signal types."""
    mock_context = {
        "data": {
            "signals": [
                {
                    "signal_type": "glucose",
                    "value": 180,
                    "unit": "mg/dL",
                    "anomalous": True,
                    "received_at": "2026-03-06T07:00:00Z",
                }
            ],
            "alerts": [],
        }
    }

    with patch("src.ai_summary.fetch_patient_context", new=AsyncMock(return_value=mock_context)):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Elevated glucose detected. Recommend follow-up.")]
        mock_anthropic_client = AsyncMock()
        mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("src.ai_summary._client", mock_anthropic_client):
            from src.ai_summary import generate_summary_with_context
            summary, cited_signals = await generate_summary_with_context(
                alert_type="glucose_high",
                severity="URGENT",
                patient_hash="sha256:abc",
                timestamp="2026-03-06T07:00:00Z",
                hasura_url="http://localhost:8080",
                hasura_secret="secret",
            )

    assert "glucose" in cited_signals
    assert isinstance(summary, str)
    assert len(summary) > 0


@pytest.mark.asyncio
async def test_generate_summary_with_context_no_signals():
    """When context has empty signals, summary is still returned and cited_signals is empty."""
    mock_context = {
        "data": {
            "signals": [],
            "alerts": [],
        }
    }

    with patch("src.ai_summary.fetch_patient_context", new=AsyncMock(return_value=mock_context)):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="No abnormal signals detected.")]
        mock_anthropic_client = AsyncMock()
        mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("src.ai_summary._client", mock_anthropic_client):
            from src.ai_summary import generate_summary_with_context
            summary, cited_signals = await generate_summary_with_context(
                alert_type="routine_check",
                severity="LOW",
                patient_hash="sha256:def",
                timestamp="2026-03-06T07:00:00Z",
                hasura_url="http://localhost:8080",
                hasura_secret="secret",
            )

    assert cited_signals == []
    assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# publish_ai_event — structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_ai_event_structure():
    """publish_ai_event publishes a canonical envelope with event_id, event_type, timestamp, etc."""
    mock_publisher = AsyncMock()

    from src.ai_events import publish_ai_event

    await publish_ai_event(
        publisher=mock_publisher,
        event_type="ai.summary.generated",
        task_id="task-abc",
        patient_id="patient-123",
        payload={"output_hash": "sha256:xyz", "context_event_ids": []},
    )

    mock_publisher.publish.assert_awaited_once()
    call_args = mock_publisher.publish.call_args
    topic = call_args.args[0]
    event = call_args.args[1]

    assert topic == "ocean.ai-ops"
    assert event["event_type"] == "ai.summary.generated"
    assert "event_id" in event
    assert "timestamp" in event
    assert event["source_system"] == "ocean"
    assert event["entity_id"] == "task-abc"
    assert "patient_id_hash" in event["payload"]
    assert "output_hash" in event["payload"]


@pytest.mark.asyncio
async def test_publish_ai_event_no_raw_patient_id():
    """The published event payload must NOT contain the raw patient_id — only sha256 hash."""
    mock_publisher = AsyncMock()
    raw_patient_id = "patient-999-raw"

    from src.ai_events import publish_ai_event

    await publish_ai_event(
        publisher=mock_publisher,
        event_type="ai.summary.generated",
        task_id="task-xyz",
        patient_id=raw_patient_id,
        payload={"output_hash": "sha256:out"},
    )

    call_args = mock_publisher.publish.call_args
    event = call_args.args[1]
    payload = event["payload"]

    # Raw patient_id must not appear anywhere in the payload
    assert raw_patient_id not in str(payload), "Raw patient_id leaked into event payload"

    # Must have a sha256 hash instead
    expected_hash = hashlib.sha256(raw_patient_id.encode()).hexdigest()
    assert payload["patient_id_hash"] == expected_hash
