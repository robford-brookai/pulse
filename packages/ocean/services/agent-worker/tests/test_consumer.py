"""Tests for agent-worker consumer, claim competition, and feedback loop guard."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.consumer import handle_message
from src.claim import compete_for_claim
from src.personas import Persona


def _make_persona(
    id: str = "coordinator_alice",
    role: str = "Senior Care Coordinator",
    delay: tuple[int, int] = (1, 2),
    human_escalation_responder: bool = False,
) -> Persona:
    return Persona(
        id=id,
        role=role,
        claim_delay_seconds=delay,
        human_escalation_responder=human_escalation_responder,
    )


def _task_created_event(
    source_system: str = "control-plane",
    event_type: str = "task.created",
    entity_id: str = "task-001",
    correlation_id: str = "corr-001",
) -> dict:
    return {
        "event_id": "evt-001",
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": "2026-03-08T12:00:00Z",
        "source_system": source_system,
        "entity_type": "task",
        "entity_id": entity_id,
        "correlation_id": correlation_id,
        "actor_id": None,
        "payload": {"priority": "urgent"},
    }


class TestFeedbackLoopGuard:
    async def test_skips_own_events(self):
        """Consumer must skip events where source_system is not control-plane."""
        event = _task_created_event(source_system="agent-worker")
        publisher = AsyncMock()
        personas = [_make_persona()]
        claimed = set()

        result = await handle_message(event, personas, publisher, claimed)
        assert result == "skipped_source"
        publisher.publish.assert_not_called()

    async def test_skips_sim_driver_events(self):
        event = _task_created_event(source_system="sim-driver")
        publisher = AsyncMock()
        result = await handle_message(event, [_make_persona()], publisher, set())
        assert result == "skipped_source"

    async def test_accepts_control_plane_events(self):
        event = _task_created_event(source_system="control-plane")
        publisher = AsyncMock()
        personas = [_make_persona()]
        claimed = set()

        with patch("src.consumer.compete_for_claim", new_callable=AsyncMock) as mock_claim:
            mock_claim.return_value = personas[0]
            result = await handle_message(event, personas, publisher, claimed)

        assert result == "dispatched"


class TestEventTypeFilter:
    async def test_skips_non_task_created(self):
        event = _task_created_event(event_type="alert.created")
        publisher = AsyncMock()
        result = await handle_message(event, [_make_persona()], publisher, set())
        assert result == "skipped_type"

    async def test_accepts_task_created(self):
        event = _task_created_event(event_type="task.created")
        publisher = AsyncMock()
        with patch("src.consumer.compete_for_claim", new_callable=AsyncMock) as mock_claim:
            mock_claim.return_value = _make_persona()
            result = await handle_message(event, [_make_persona()], publisher, set())
        assert result == "dispatched"


class TestClaimCompetition:
    async def test_excludes_escalation_responders(self):
        alice = _make_persona(id="alice", delay=(0, 0))
        carol = _make_persona(id="carol", human_escalation_responder=True, delay=(0, 0))
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event()

        winner = await compete_for_claim(
            event, [alice, carol], publisher, claimed, compression_ratio=100000,
        )
        assert winner is not None
        assert winner.id == "alice"

    async def test_publishes_task_claimed(self):
        alice = _make_persona(id="alice", delay=(0, 0))
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event(entity_id="task-100", correlation_id="corr-100")

        await compete_for_claim(
            event, [alice], publisher, claimed, compression_ratio=100000,
        )
        publisher.publish.assert_called_once()
        call_args = publisher.publish.call_args
        assert call_args[0][0] == "ocean.tasks"
        published_event = call_args[0][1]
        assert published_event["event_type"] == "task.claimed"
        assert published_event["source_system"] == "agent-worker"
        assert published_event["correlation_id"] == "corr-100"
        assert published_event["entity_id"] == "task-100"

    async def test_duplicate_claim_prevented(self):
        alice = _make_persona(id="alice", delay=(0, 0))
        publisher = AsyncMock()
        claimed = {"task-100"}
        event = _task_created_event(entity_id="task-100")

        winner = await compete_for_claim(
            event, [alice], publisher, claimed, compression_ratio=100000,
        )
        assert winner is None
        publisher.publish.assert_not_called()

    async def test_returns_none_when_no_eligible_personas(self):
        carol = _make_persona(id="carol", human_escalation_responder=True)
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event()

        winner = await compete_for_claim(
            event, [carol], publisher, claimed, compression_ratio=100000,
        )
        assert winner is None
        publisher.publish.assert_not_called()

    async def test_claimed_set_updated(self):
        alice = _make_persona(id="alice", delay=(0, 0))
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event(entity_id="task-200")

        await compete_for_claim(
            event, [alice], publisher, claimed, compression_ratio=100000,
        )
        assert "task-200" in claimed


class TestHealthEndpoint:
    async def test_health(self):
        from src.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "agent-worker"
