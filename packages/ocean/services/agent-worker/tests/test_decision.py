"""Tests for decision pipeline, fallback, and event builders."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.personas import Persona


def _make_persona(
    id: str = "coordinator_alice",
    role: str = "Senior Care Coordinator",
    outreach_approve_rate: float = 0.8,
    call_answer_rate: float = 0.8,
    missed_call_retry_count: int = 1,
    retry_delay_seconds: int = 120,
) -> Persona:
    return Persona(
        id=id,
        role=role,
        claim_delay_seconds=(1, 2),
        outreach_approve_rate=outreach_approve_rate,
        call_answer_rate=call_answer_rate,
        missed_call_retry_count=missed_call_retry_count,
        retry_delay_seconds=retry_delay_seconds,
    )


def _alert_context(
    priority: str = "urgent",
    signal_type: str = "glucose",
    severity: str = "URGENT",
    patient_id: str = "patient-001",
) -> dict:
    return {
        "priority": priority,
        "signal_type": signal_type,
        "severity": severity,
        "patient_id": patient_id,
    }


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------

class TestDeterministicFallback:
    def test_critical_always_approves(self):
        from src.fallback import deterministic_fallback

        action, confidence = deterministic_fallback(
            _alert_context(severity="CRITICAL", signal_type="heart_rate")
        )
        assert action == "approve"
        assert confidence == 1.0

    def test_urgent_glucose_approves(self):
        from src.fallback import deterministic_fallback

        action, confidence = deterministic_fallback(
            _alert_context(severity="URGENT", signal_type="glucose")
        )
        assert action == "approve"
        assert confidence == 0.8

    def test_urgent_spo2_approves(self):
        from src.fallback import deterministic_fallback

        action, confidence = deterministic_fallback(
            _alert_context(severity="URGENT", signal_type="spo2")
        )
        assert action == "approve"
        assert confidence == 0.8

    def test_urgent_other_escalates(self):
        from src.fallback import deterministic_fallback

        action, confidence = deterministic_fallback(
            _alert_context(severity="URGENT", signal_type="weight")
        )
        assert action == "escalate"
        assert confidence == 0.5

    def test_high_escalates(self):
        from src.fallback import deterministic_fallback

        action, confidence = deterministic_fallback(
            _alert_context(severity="HIGH", signal_type="glucose")
        )
        assert action == "escalate"
        assert confidence == 0.3

    def test_low_severity_escalates(self):
        from src.fallback import deterministic_fallback

        action, confidence = deterministic_fallback(
            _alert_context(severity="LOW", signal_type="glucose")
        )
        assert action == "escalate"
        assert confidence == 0.3

    def test_uses_priority_when_severity_missing(self):
        from src.fallback import deterministic_fallback

        ctx = {"priority": "critical", "signal_type": "glucose"}
        action, confidence = deterministic_fallback(ctx)
        assert action == "approve"
        assert confidence == 1.0


# ---------------------------------------------------------------------------
# Decision pipeline tests (mocked Anthropic)
# ---------------------------------------------------------------------------

class TestGenerateOutreachDecision:
    async def test_returns_action_and_reasoning(self):
        from src.decision import generate_outreach_decision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"action": "approve", "reasoning": "Critical glucose reading"}')]

        with patch("src.decision._client") as mock_client:
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            result = await generate_outreach_decision(_alert_context())

        assert result["action"] == "approve"
        assert "reasoning" in result

    async def test_uses_haiku_model(self):
        from src.decision import generate_outreach_decision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"action": "approve", "reasoning": "test"}')]

        with patch("src.decision._client") as mock_client:
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            await generate_outreach_decision(_alert_context())

            call_kwargs = mock_client.messages.create.call_args[1]
            assert "haiku" in call_kwargs["model"]


class TestJudgeDecision:
    async def test_returns_float_confidence(self):
        from src.decision import judge_decision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"confidence": 0.85}')]

        with patch("src.decision._client") as mock_client:
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            confidence = await judge_decision(
                {"action": "approve", "reasoning": "test"}, _alert_context()
            )

        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0


class TestDecideWithFallback:
    async def test_uses_haiku_when_available(self):
        from src.decision import decide_with_fallback

        # Mock both calls: decision + judge
        decision_response = MagicMock()
        decision_response.content = [MagicMock(text='{"action": "approve", "reasoning": "critical reading"}')]
        judge_response = MagicMock()
        judge_response.content = [MagicMock(text='{"confidence": 0.9}')]

        with patch("src.decision._client") as mock_client:
            mock_client.messages.create = AsyncMock(
                side_effect=[decision_response, judge_response]
            )
            action, confidence = await decide_with_fallback(_alert_context())

        assert action == "approve"
        assert confidence == 0.9

    async def test_falls_back_on_api_error(self):
        from src.decision import decide_with_fallback

        with patch("src.decision._client") as mock_client:
            mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))
            action, confidence = await decide_with_fallback(
                _alert_context(severity="CRITICAL")
            )

        # Should use deterministic fallback
        assert action == "approve"
        assert confidence == 1.0

    async def test_falls_back_on_parse_error(self):
        from src.decision import decide_with_fallback

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not json at all")]

        with patch("src.decision._client") as mock_client:
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            action, confidence = await decide_with_fallback(
                _alert_context(severity="URGENT", signal_type="spo2")
            )

        assert action == "approve"
        assert confidence == 0.8


# ---------------------------------------------------------------------------
# Event builder tests
# ---------------------------------------------------------------------------

class TestBuildAgentEvent:
    def test_envelope_shape(self):
        from src.events import build_agent_event

        event = build_agent_event(
            event_type="ai.recommendation.generated",
            entity_id="task-001",
            entity_type="task",
            correlation_id="corr-001",
            payload={"action": "approve"},
        )

        assert event["event_type"] == "ai.recommendation.generated"
        assert event["source_system"] == "agent-worker"
        assert event["entity_id"] == "task-001"
        assert event["entity_type"] == "task"
        assert event["correlation_id"] == "corr-001"
        assert event["schema_version"] == "1.0.0"
        assert "event_id" in event
        assert "timestamp" in event
        assert event["payload"]["action"] == "approve"


class TestPublishAiRecommendation:
    async def test_publishes_to_ai_ops(self):
        from src.events import publish_ai_recommendation

        publisher = AsyncMock()
        task_data = {
            "entity_id": "task-001",
            "correlation_id": "corr-001",
        }
        persona = _make_persona()

        await publish_ai_recommendation(
            publisher, task_data, "approve", 0.9, persona
        )

        publisher.publish.assert_called_once()
        call_args = publisher.publish.call_args
        assert call_args[0][0] == "ocean.ai-ops"
        event = call_args[0][1]
        assert event["event_type"] == "ai.recommendation.generated"
        assert event["payload"]["action"] == "approve"
        assert event["payload"]["confidence"] == 0.9
        assert event["payload"]["persona_id"] == "coordinator_alice"


class TestPublishAiDecision:
    async def test_approved_includes_call_config(self):
        from src.events import publish_ai_decision

        publisher = AsyncMock()
        task_data = {
            "entity_id": "task-001",
            "correlation_id": "corr-001",
        }
        persona = _make_persona(
            call_answer_rate=0.8,
            missed_call_retry_count=1,
            retry_delay_seconds=120,
        )

        await publish_ai_decision(
            publisher, task_data, "approve", 0.9, persona, approved=True
        )

        call_args = publisher.publish.call_args
        assert call_args[0][0] == "ocean.ai-ops"
        event = call_args[0][1]
        assert event["event_type"] == "ai.output.approved"
        payload = event["payload"]
        assert payload["call_answer_rate"] == 0.8
        assert payload["missed_call_retry_count"] == 1
        assert payload["retry_delay_seconds"] == 120
        assert "compression_ratio" in payload

    async def test_rejected_event_type(self):
        from src.events import publish_ai_decision

        publisher = AsyncMock()
        task_data = {
            "entity_id": "task-001",
            "correlation_id": "corr-001",
        }
        persona = _make_persona()

        await publish_ai_decision(
            publisher, task_data, "escalate", 0.3, persona, approved=False
        )

        event = publisher.publish.call_args[0][1]
        assert event["event_type"] == "ai.output.rejected"

    async def test_publish_error_does_not_raise(self):
        from src.events import publish_ai_decision

        publisher = AsyncMock()
        publisher.publish.side_effect = Exception("Redpanda down")
        task_data = {"entity_id": "task-001", "correlation_id": "corr-001"}
        persona = _make_persona()

        # Should not raise
        await publish_ai_decision(
            publisher, task_data, "approve", 0.9, persona, approved=True
        )


class TestPublishTaskCompleted:
    async def test_publishes_to_tasks_topic(self):
        from src.events import publish_task_completed

        publisher = AsyncMock()
        task_data = {
            "entity_id": "task-001",
            "correlation_id": "corr-001",
        }
        persona = _make_persona()

        await publish_task_completed(publisher, task_data, persona)

        call_args = publisher.publish.call_args
        assert call_args[0][0] == "ocean.tasks"
        event = call_args[0][1]
        assert event["event_type"] == "task.completed"
        assert event["source_system"] == "agent-worker"
        assert event["payload"]["persona_id"] == "coordinator_alice"
