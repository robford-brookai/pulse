"""Tests for agent-worker consumer, claim competition, and feedback loop guard."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.claim import compete_for_claim
from src.consumer import handle_message, run_consumer
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
    patient_id: str = "pt-001",
    severity: str = "CRITICAL",
    signal_type: str = "glucose",
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
        "payload": {
            "priority": "urgent",
            "patient_id": patient_id,
            "severity": severity,
            "signal_type": signal_type,
        },
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
            event,
            [alice, carol],
            publisher,
            claimed,
            compression_ratio=100000,
        )
        assert winner is not None
        assert winner.id == "alice"

    async def test_publishes_task_claimed(self):
        alice = _make_persona(id="alice", delay=(0, 0))
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event(entity_id="task-100", correlation_id="corr-100")

        await compete_for_claim(
            event,
            [alice],
            publisher,
            claimed,
            compression_ratio=100000,
        )
        publisher.publish.assert_called_once()
        call_args = publisher.publish.call_args
        assert call_args[0][0] == "tasks"
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
            event,
            [alice],
            publisher,
            claimed,
            compression_ratio=100000,
        )
        assert winner is None
        publisher.publish.assert_not_called()

    async def test_returns_none_when_no_eligible_personas(self):
        carol = _make_persona(id="carol", human_escalation_responder=True)
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event()

        winner = await compete_for_claim(
            event,
            [carol],
            publisher,
            claimed,
            compression_ratio=100000,
        )
        assert winner is None
        publisher.publish.assert_not_called()

    async def test_claimed_set_updated(self):
        alice = _make_persona(id="alice", delay=(0, 0))
        publisher = AsyncMock()
        claimed = set()
        event = _task_created_event(entity_id="task-200")

        await compete_for_claim(
            event,
            [alice],
            publisher,
            claimed,
            compression_ratio=100000,
        )
        assert "task-200" in claimed


class TestAlertContextBuilding:
    """Verify alert_context is built correctly from task.created payload."""

    async def test_patient_id_from_payload(self):
        """patient_id should come from payload.patient_id, not entity_id."""
        event = _task_created_event(entity_id="task-001", patient_id="pt-abc")
        publisher = AsyncMock()
        persona = _make_persona()

        with (
            patch("src.consumer.compete_for_claim", new_callable=AsyncMock) as mock_claim,
            patch("src.consumer.decide_with_fallback", new_callable=AsyncMock) as mock_decide,
            patch("src.consumer.publish_ai_recommendation", new_callable=AsyncMock),
            patch("src.consumer.publish_ai_decision", new_callable=AsyncMock) as mock_decision,
            patch("src.consumer.publish_task_completed", new_callable=AsyncMock),
        ):
            mock_claim.return_value = persona
            mock_decide.return_value = ("approve", 1.0)
            await handle_message(event, [persona], publisher, set())

            # publish_ai_decision receives alert_context with patient_id
            call_args = mock_decision.call_args
            alert_context = call_args[0][6]  # 7th positional arg
            assert alert_context["patient_id"] == "pt-abc"

    async def test_severity_from_payload(self):
        """severity should come from payload.severity."""
        event = _task_created_event(severity="URGENT")
        publisher = AsyncMock()
        persona = _make_persona()

        with (
            patch("src.consumer.compete_for_claim", new_callable=AsyncMock) as mock_claim,
            patch("src.consumer.decide_with_fallback", new_callable=AsyncMock) as mock_decide,
            patch("src.consumer.publish_ai_recommendation", new_callable=AsyncMock),
            patch("src.consumer.publish_ai_decision", new_callable=AsyncMock) as mock_decision,
            patch("src.consumer.publish_task_completed", new_callable=AsyncMock),
        ):
            mock_claim.return_value = persona
            mock_decide.return_value = ("approve", 1.0)
            await handle_message(event, [persona], publisher, set())

            call_args = mock_decision.call_args
            alert_context = call_args[0][6]
            assert alert_context["severity"] == "URGENT"

    async def test_signal_type_anomaly_suffix_stripped(self):
        """signal_type 'glucose_anomaly' should resolve to 'glucose'."""
        event = _task_created_event(signal_type="glucose_anomaly")
        publisher = AsyncMock()
        persona = _make_persona()

        with (
            patch("src.consumer.compete_for_claim", new_callable=AsyncMock) as mock_claim,
            patch("src.consumer.decide_with_fallback", new_callable=AsyncMock) as mock_decide,
            patch("src.consumer.publish_ai_recommendation", new_callable=AsyncMock),
            patch("src.consumer.publish_ai_decision", new_callable=AsyncMock) as mock_decision,
            patch("src.consumer.publish_task_completed", new_callable=AsyncMock),
        ):
            mock_claim.return_value = persona
            mock_decide.return_value = ("approve", 0.8)
            await handle_message(event, [persona], publisher, set())

            call_args = mock_decision.call_args
            alert_context = call_args[0][6]
            assert alert_context["signal_type"] == "glucose"


class TestApprovalEventPayload:
    """Verify approved events include patient_id, severity, signal_type."""

    async def test_approved_event_includes_patient_id(self):
        """ai.output.approved must include patient_id for call-simulator."""
        from src.events import publish_ai_decision

        publisher = AsyncMock()
        task_data = {"entity_id": "task-001", "correlation_id": "corr-001"}
        persona = _make_persona()
        alert_context = {"patient_id": "pt-xyz", "severity": "CRITICAL", "signal_type": "glucose"}

        await publish_ai_decision(publisher, task_data, "approve", 1.0, persona, True, alert_context)

        call_args = publisher.publish.call_args
        event = call_args[0][1]
        assert event["payload"]["patient_id"] == "pt-xyz"

    async def test_approved_event_includes_severity(self):
        from src.events import publish_ai_decision

        publisher = AsyncMock()
        task_data = {"entity_id": "task-001", "correlation_id": "corr-001"}
        persona = _make_persona()
        alert_context = {"patient_id": "pt-xyz", "severity": "URGENT", "signal_type": "spo2"}

        await publish_ai_decision(publisher, task_data, "approve", 0.8, persona, True, alert_context)

        call_args = publisher.publish.call_args
        event = call_args[0][1]
        assert event["payload"]["severity"] == "URGENT"
        assert event["payload"]["signal_type"] == "spo2"


class TestHealthEndpoint:
    async def test_health(self):
        from fastapi.testclient import TestClient
        from src.main import app

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "agent-worker"


class TestResetEndpoint:
    """POST /reset clears _claimed_tasks and returns 200."""

    async def test_reset_returns_ok(self):
        from fastapi.testclient import TestClient
        from src.main import app

        client = TestClient(app)
        resp = client.post("/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["claimed_tasks_cleared"] is True

    async def test_reset_clears_claimed_tasks(self):
        from fastapi.testclient import TestClient
        from src.main import _claimed_tasks, app

        # Add items to _claimed_tasks
        _claimed_tasks.add("task-aaa")
        _claimed_tasks.add("task-bbb")
        assert len(_claimed_tasks) >= 2

        client = TestClient(app)
        resp = client.post("/reset")
        assert resp.status_code == 200
        assert len(_claimed_tasks) == 0


def _eventbridge_sqs_message(envelope: dict, receipt_handle: str = "rh-1") -> dict:
    """Build the SQS message an EventBridge rule delivers: envelope inside ``detail``."""
    body = {
        "version": "0",
        "id": "eb-msg-001",
        "detail-type": "tasks",
        "source": "ocean",
        "account": "000000000000",
        "time": "2026-03-08T12:00:00Z",
        "region": "us-east-1",
        "detail": envelope,
    }
    return {"Body": json.dumps(body), "ReceiptHandle": receipt_handle}


def _sqs_client(*receive_results: dict) -> Mock:
    """Sync boto3-shaped SQS client: yields each receive result, then cancels the loop."""
    client = Mock()
    client.receive_message = Mock(side_effect=[*receive_results, asyncio.CancelledError()])
    client.delete_message = Mock()
    return client


class TestSqsLoop:
    """run_consumer polls SQS, unwraps the EventBridge body, deletes only after success."""

    async def test_unwraps_detail_and_processes_envelope(self):
        envelope = _task_created_event()
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope)]})
        publisher = AsyncMock()
        personas = [_make_persona()]

        with (
            pytest.raises(asyncio.CancelledError),
            patch("src.consumer.handle_message", new_callable=AsyncMock) as mock_handle,
        ):
            await run_consumer(personas, "https://sqs.test/agent-worker", publisher, set(), sqs_client=client)

        mock_handle.assert_awaited_once()
        assert mock_handle.await_args[0][0] == envelope

    async def test_deletes_after_successful_processing(self):
        envelope = _task_created_event()
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope, receipt_handle="rh-ok")]})
        publisher = AsyncMock()

        with (
            pytest.raises(asyncio.CancelledError),
            patch("src.consumer.handle_message", new_callable=AsyncMock),
        ):
            await run_consumer([_make_persona()], "https://sqs.test/q", publisher, set(), sqs_client=client)

        client.delete_message.assert_called_once_with(QueueUrl="https://sqs.test/q", ReceiptHandle="rh-ok")

    async def test_failure_leaves_message_for_redelivery(self):
        envelope = _task_created_event()
        client = _sqs_client({"Messages": [_eventbridge_sqs_message(envelope)]})
        publisher = AsyncMock()

        with (
            pytest.raises(asyncio.CancelledError),
            patch("src.consumer.handle_message", new_callable=AsyncMock) as mock_handle,
        ):
            mock_handle.side_effect = RuntimeError("boom")
            await run_consumer([_make_persona()], "https://sqs.test/q", publisher, set(), sqs_client=client)

        client.delete_message.assert_not_called()

    async def test_malformed_body_not_deleted(self):
        client = _sqs_client({"Messages": [{"Body": "not json{{{", "ReceiptHandle": "rh-bad"}]})
        publisher = AsyncMock()

        with (
            pytest.raises(asyncio.CancelledError),
            patch("src.consumer.handle_message", new_callable=AsyncMock) as mock_handle,
        ):
            await run_consumer([_make_persona()], "https://sqs.test/q", publisher, set(), sqs_client=client)

        mock_handle.assert_not_awaited()
        client.delete_message.assert_not_called()

    async def test_bare_envelope_without_detail_is_accepted(self):
        envelope = _task_created_event()
        msg = {"Body": json.dumps(envelope), "ReceiptHandle": "rh-2"}
        client = _sqs_client({"Messages": [msg]})
        publisher = AsyncMock()

        with (
            pytest.raises(asyncio.CancelledError),
            patch("src.consumer.handle_message", new_callable=AsyncMock) as mock_handle,
        ):
            await run_consumer([_make_persona()], "https://sqs.test/q", publisher, set(), sqs_client=client)

        assert mock_handle.await_args[0][0] == envelope

    async def test_empty_receive_continues_polling(self):
        client = _sqs_client({}, {"Messages": []})
        publisher = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await run_consumer([_make_persona()], "https://sqs.test/q", publisher, set(), sqs_client=client)

        assert client.receive_message.call_count == 3


class TestOrderTolerance:
    """Verdict evidence: one event type, one source — delivery order cannot change final state."""

    async def _run_events(self, events: list[dict]) -> tuple[set, list]:
        claimed: set[str] = set()
        publisher = AsyncMock()
        persona = _make_persona(delay=(0, 0))
        with (
            patch("src.consumer.decide_with_fallback", new_callable=AsyncMock) as mock_decide,
            patch("src.consumer.publish_ai_recommendation", new_callable=AsyncMock),
            patch("src.consumer.publish_ai_decision", new_callable=AsyncMock),
            patch("src.consumer.publish_task_completed", new_callable=AsyncMock),
        ):
            mock_decide.return_value = ("approve", 1.0)
            results = [await handle_message(e, [persona], publisher, claimed) for e in events]
        return claimed, results

    async def test_reverse_delivery_reaches_same_state(self):
        events = [
            _task_created_event(entity_id="task-A", correlation_id="corr-A"),
            _task_created_event(entity_id="task-B", correlation_id="corr-B"),
        ]
        claimed_forward, results_forward = await self._run_events(events)
        claimed_reverse, results_reverse = await self._run_events(list(reversed(events)))

        assert claimed_forward == claimed_reverse == {"task-A", "task-B"}
        assert results_forward == results_reverse == ["dispatched", "dispatched"]


class TestRerunAfterReset:
    """After claiming, resetting, and re-submitting the same event, it dispatches."""

    async def test_rerun_dispatches_after_reset(self):
        from fastapi.testclient import TestClient
        from src.main import _claimed_tasks, app

        # 1. Add entity_id to claimed set (simulating a prior claim)
        _claimed_tasks.add("task-001")

        # 2. Call /reset to clear
        client = TestClient(app)
        resp = client.post("/reset")
        assert resp.status_code == 200
        assert len(_claimed_tasks) == 0

        # 3. Submit the same task.created event -- should dispatch, not skip
        event = _task_created_event(entity_id="task-001")
        publisher = AsyncMock()
        personas = [_make_persona(delay=(0, 0))]

        with patch("src.consumer.compete_for_claim", new_callable=AsyncMock) as mock_claim:
            mock_claim.return_value = personas[0]
            result = await handle_message(event, personas, publisher, _claimed_tasks)

        assert result == "dispatched"
