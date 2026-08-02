"""Tests for call simulation logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.call_sim import build_call_event, simulate_call


def _make_approval_event(
    *,
    call_answer_rate: float = 0.80,
    missed_call_retry_count: int = 1,
    retry_delay_seconds: int = 120,
    compression_ratio: int = 960,
) -> dict:
    return {
        "event_id": "approval-evt-001",
        "event_type": "ai.output.approved",
        "source_system": "agent-worker",
        "entity_type": "task",
        "entity_id": "task-001",
        "correlation_id": "corr-abc-123",
        "payload": {
            "patient_id": "patient-42",
            "persona_id": "coordinator_alice",
            "call_answer_rate": call_answer_rate,
            "missed_call_retry_count": missed_call_retry_count,
            "retry_delay_seconds": retry_delay_seconds,
            "compression_ratio": compression_ratio,
            "decision": "approve",
            "confidence": 0.85,
        },
    }


class TestBuildCallEvent:
    def test_envelope_fields(self):
        evt = build_call_event(
            event_type="call.started",
            entity_id="int-001",
            correlation_id="corr-abc",
            payload={"patient_id": "p1", "persona_id": "coord_a"},
        )
        assert evt["event_type"] == "call.started"
        assert evt["source_system"] == "call-simulator"
        assert evt["entity_type"] == "interaction"
        assert evt["entity_id"] == "int-001"
        assert evt["correlation_id"] == "corr-abc"
        assert "event_id" in evt
        assert "timestamp" in evt
        assert evt["schema_version"] == "1.0.0"

    def test_payload_passed_through(self):
        payload = {"patient_id": "p1", "persona_id": "coord_a", "extra": "data"}
        evt = build_call_event(
            event_type="call.connected",
            entity_id="int-002",
            correlation_id="corr-xyz",
            payload=payload,
        )
        assert evt["payload"]["patient_id"] == "p1"
        assert evt["payload"]["extra"] == "data"


class TestSimulateCallAnswered:
    """Call answered on first attempt: started -> connected -> completed."""

    async def test_answered_call_event_sequence(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=1.0)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", new_callable=AsyncMock):
            mock_random.random.return_value = 0.5  # < 1.0 = answered
            mock_random.uniform.return_value = 10.0

            await simulate_call(approval, publisher)

        calls = publisher.publish.call_args_list
        topics = [c.args[0] for c in calls]
        event_types = [c.args[1]["event_type"] for c in calls]

        assert all(t == "ocean.interactions" for t in topics)
        assert event_types == ["call.started", "call.connected", "call.completed"]

    async def test_answered_call_propagates_correlation_id(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=1.0)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", new_callable=AsyncMock):
            mock_random.random.return_value = 0.5
            mock_random.uniform.return_value = 10.0

            await simulate_call(approval, publisher)

        for call in publisher.publish.call_args_list:
            evt = call.args[1]
            assert evt["correlation_id"] == "corr-abc-123"

    async def test_answered_call_includes_duration(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=1.0, compression_ratio=960)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", new_callable=AsyncMock):
            mock_random.random.return_value = 0.5
            mock_random.uniform.return_value = 120.0  # sim-seconds

            await simulate_call(approval, publisher)

        completed_evt = publisher.publish.call_args_list[2].args[1]
        assert completed_evt["event_type"] == "call.completed"
        assert "duration_seconds" in completed_evt["payload"]


class TestSimulateCallMissed:
    """Call missed with zero retries: started -> missed."""

    async def test_missed_no_retry(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=0.0, missed_call_retry_count=0)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", new_callable=AsyncMock):
            mock_random.random.return_value = 0.99  # > 0.0 = missed
            mock_random.uniform.return_value = 10.0

            await simulate_call(approval, publisher)

        event_types = [c.args[1]["event_type"] for c in publisher.publish.call_args_list]
        assert event_types == ["call.started", "call.missed"]


class TestSimulateCallMissedThenRetrySuccess:
    """Missed first, retry succeeds: started -> missed -> started -> connected -> completed."""

    async def test_retry_success(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=0.5, missed_call_retry_count=1)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", new_callable=AsyncMock):
            # First call: miss (0.99 > 0.5), retry: answer (0.1 < 0.5)
            mock_random.random.side_effect = [0.99, 0.1]
            mock_random.uniform.return_value = 10.0

            await simulate_call(approval, publisher)

        event_types = [c.args[1]["event_type"] for c in publisher.publish.call_args_list]
        assert event_types == [
            "call.started",
            "call.missed",
            "call.started",
            "call.connected",
            "call.completed",
        ]


class TestSimulateCallSourceSystem:
    """All events have source_system='call-simulator' and entity_type='interaction'."""

    async def test_all_events_source_and_entity(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=1.0)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", new_callable=AsyncMock):
            mock_random.random.return_value = 0.5
            mock_random.uniform.return_value = 10.0

            await simulate_call(approval, publisher)

        for call in publisher.publish.call_args_list:
            evt = call.args[1]
            assert evt["source_system"] == "call-simulator"
            assert evt["entity_type"] == "interaction"


class TestSimulateCallTiming:
    """Verify sleep durations use compression_ratio."""

    async def test_ring_delay_compressed(self):
        publisher = AsyncMock()
        approval = _make_approval_event(call_answer_rate=1.0, compression_ratio=960)
        sleep_calls = []

        async def mock_sleep(duration):
            sleep_calls.append(duration)

        with patch("src.call_sim.random") as mock_random, patch("src.call_sim.asyncio.sleep", side_effect=mock_sleep):
            mock_random.random.return_value = 0.5
            mock_random.uniform.return_value = 9.6  # sim-seconds

            await simulate_call(approval, publisher)

        # ring delay = 9.6 / 960 = 0.01
        assert abs(sleep_calls[0] - 0.01) < 0.001
