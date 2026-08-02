"""Tests for github-connector's publish path after the EventBridge conversion.

Three things must hold, and they are the three the `event-transport` spec asks of a converted
publish site:

* every publish leaves through the shared ``EventBridgePublisher``, not service-local transport
  code;
* the domain is the ``detail-type`` — ``signals`` for webhooks, ``ops`` for heartbeats — and the
  envelope crosses whole, with ``event_type`` still an envelope field;
* a bus failure writes ``failed_webhooks`` and does not raise at the call site.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ocean_broker import EventBridgePublisher

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _envelope() -> dict[str, Any]:
    return {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "event_type": "pr.merged",
        "schema_version": "1.0.0",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "source_system": "github-connector",
        "entity_type": "pull_request",
        "entity_id": "brookai/ocean#42",
        "correlation_id": "22222222-2222-2222-2222-222222222222",
        "actor_id": None,
        "payload": {"title": "Add feature X"},
    }


class _FakeSession:
    """Minimal async session recording the statements the DLQ write issues."""

    def __init__(self, recorder: list[tuple[str, dict[str, Any]]]) -> None:
        self._recorder = recorder

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def begin(self) -> _FakeSession:
        return self

    async def execute(self, statement: object, params: dict[str, Any]) -> None:
        self._recorder.append((str(statement), params))


class TestServiceLocalTransportIsGone:
    def test_no_bus_client_in_service_source(self) -> None:
        """No source file references a bus client directly (event-transport, shared publisher)."""
        offenders = [
            path.relative_to(SERVICE_ROOT)
            for path in sorted((SERVICE_ROOT / "src").rglob("*.py"))
            if "confluent_kafka" in path.read_text()
        ]
        assert offenders == []

    def test_producer_module_removed(self) -> None:
        """The service-local Redpanda producer is deleted, not wrapped."""
        assert not (SERVICE_ROOT / "src" / "producer.py").exists()


class _StubTask:
    """Stands in for the heartbeat task: cancellable, awaitable, never scheduled."""

    def cancel(self) -> None:
        return None

    def __await__(self):
        async def _done() -> None:
            return None

        return _done().__await__()


def _stub_create_task(coro: Any) -> _StubTask:
    coro.close()
    return _StubTask()


class TestLifespanWiring:
    @pytest.mark.asyncio
    async def test_lifespan_builds_shared_publisher_with_dlq(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lifespan constructs EventBridgePublisher and hands it the Postgres session maker."""
        import src.main as main_mod

        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ocean:changeme@localhost/ocean")

        engine = MagicMock()
        engine.dispose = AsyncMock()
        session_maker = MagicMock()
        publisher = MagicMock()

        with (
            patch.object(main_mod, "create_async_engine", return_value=engine),
            patch.object(main_mod, "async_sessionmaker", return_value=session_maker),
            patch.object(main_mod, "EventBridgePublisher", return_value=publisher) as mock_publisher_cls,
            patch.object(main_mod.asyncio, "create_task", _stub_create_task),
        ):
            app = MagicMock()
            async with main_mod.lifespan(app):
                pass

        mock_publisher_cls.assert_called_once_with(db_session_maker=session_maker)
        assert app.state.publisher is publisher
        engine.dispose.assert_awaited_once()


class TestWebhookPublishAddressing:
    @pytest.mark.asyncio
    async def test_webhook_publishes_to_signals_domain(self) -> None:
        """A normalized webhook publishes with detail-type 'signals', keyed by entity_id."""
        import src.receiver as receiver_mod

        event = _envelope()
        publisher = AsyncMock()
        request = MagicMock()
        request.app.state.publisher = publisher
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {"x-hub-signature-256": "", "x-github-event": "pull_request"}

        with (
            patch.object(receiver_mod, "_validate_github_signature"),
            patch.object(receiver_mod, "normalize_event", return_value=event),
        ):
            result = await receiver_mod.receive_github_webhook(request)

        assert result == {"status": "accepted"}
        publisher.publish.assert_awaited_once_with(
            detail_type="signals",
            event=event,
            key="brookai/ocean#42",
        )

    @pytest.mark.asyncio
    async def test_event_type_is_not_promoted_to_detail_type(self) -> None:
        """detail-type is the domain; event_type stays an envelope field."""
        import src.receiver as receiver_mod

        event = _envelope()
        publisher = AsyncMock()
        request = MagicMock()
        request.app.state.publisher = publisher
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {"x-hub-signature-256": "", "x-github-event": "pull_request"}

        with (
            patch.object(receiver_mod, "_validate_github_signature"),
            patch.object(receiver_mod, "normalize_event", return_value=event),
        ):
            await receiver_mod.receive_github_webhook(request)

        kwargs = publisher.publish.await_args.kwargs
        assert kwargs["detail_type"] == "signals"
        assert kwargs["event"]["event_type"] == "pr.merged"


class _StopLoop(Exception):
    """Breaks the heartbeat's infinite loop after exactly one tick."""


class TestHeartbeatPublishAddressing:
    @pytest.mark.asyncio
    async def test_heartbeat_publishes_to_ops_domain(self) -> None:
        """The heartbeat loop publishes one envelope per tick with detail-type 'ops'."""
        import src.heartbeat as heartbeat_mod

        publisher = AsyncMock()

        with patch.object(heartbeat_mod.asyncio, "sleep", side_effect=_StopLoop), pytest.raises(_StopLoop):
            await heartbeat_mod.publish_heartbeat(publisher, "github-connector", "GitHub PR/Commit Signals")

        kwargs = publisher.publish.await_args.kwargs
        assert kwargs["detail_type"] == "ops"
        assert kwargs["key"] == "github-connector"
        assert kwargs["event"]["event_type"] == "connector.heartbeat"
        assert isinstance(kwargs["event"], dict)


class TestPublishFailureFallback:
    @pytest.mark.asyncio
    async def test_bus_failure_writes_failed_webhooks_and_does_not_raise(self) -> None:
        """A bus rejection lands in failed_webhooks; the caller sees no exception."""
        recorder: list[tuple[str, dict[str, Any]]] = []
        client = MagicMock()
        client.put_events.side_effect = RuntimeError("bus unavailable")

        with patch("ocean_broker.publisher.boto3.client", return_value=client):
            publisher = EventBridgePublisher(db_session_maker=lambda: _FakeSession(recorder))
            await publisher.publish(detail_type="signals", event=_envelope(), key="brookai/ocean#42")

        assert len(recorder) == 1
        statement, params = recorder[0]
        assert "INSERT INTO failed_webhooks" in statement
        assert params["key"] == "brookai/ocean#42"
        assert params["error"] == "bus unavailable"
        payload = json.loads(params["payload"])
        assert payload["event_type"] == "pr.merged"
        assert payload["key"] == "brookai/ocean#42"
