"""Tests for bolt_app action handlers: claim and resolve."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_body(action_id: str, task_id: str = "task-abc123") -> dict:
    return {
        "actions": [{"action_id": action_id, "value": task_id}],
        "user": {"id": "U_ACTOR"},
        "container": {"channel_id": "C_CHANNEL", "message_ts": "1234567890.123456"},
    }


def _make_mock_result(has_row: bool) -> MagicMock:
    """Return a mock SQLAlchemy CursorResult whose fetchone() simulates a row or None."""
    result = MagicMock()
    result.fetchone.return_value = MagicMock() if has_row else None
    return result


# ---------------------------------------------------------------------------
# handle_task_claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_ack_called_first():
    """ack() must be the very first await in handle_task_claim."""
    call_log: list[str] = []

    async def tracking_ack():
        call_log.append("ack")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(True))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_client.chat_update = AsyncMock(side_effect=lambda **kw: call_log.append("chat_update"))

    from src.bolt_app import handle_task_claim, set_publisher, set_session_maker

    mock_publisher = AsyncMock()
    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    await handle_task_claim(
        ack=tracking_ack,
        body=_make_body("task_claim"),
        client=mock_client,
    )

    assert call_log[0] == "ack", f"ack() was not first; order was {call_log}"


@pytest.mark.asyncio
async def test_claim_success_calls_chat_update():
    """When UPDATE returns a row, chat_update is called (not chat_postEphemeral)."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(True))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_publisher = AsyncMock()

    from src.bolt_app import handle_task_claim, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    await handle_task_claim(
        ack=AsyncMock(),
        body=_make_body("task_claim"),
        client=mock_client,
    )

    mock_client.chat_update.assert_awaited_once()
    mock_client.chat_postEphemeral.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_duplicate_calls_ephemeral():
    """When UPDATE returns no row (already claimed), chat_postEphemeral is called."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(False))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_publisher = AsyncMock()

    from src.bolt_app import handle_task_claim, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    await handle_task_claim(
        ack=AsyncMock(),
        body=_make_body("task_claim"),
        client=mock_client,
    )

    mock_client.chat_postEphemeral.assert_awaited_once()
    call_kwargs = mock_client.chat_postEphemeral.call_args.kwargs
    assert "already been claimed" in call_kwargs["text"]
    mock_client.chat_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_duplicate_does_not_publish_event():
    """When claim fails (already claimed), no event is published."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(False))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_publisher = AsyncMock()

    from src.bolt_app import handle_task_claim, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    await handle_task_claim(
        ack=AsyncMock(),
        body=_make_body("task_claim"),
        client=mock_client,
    )

    mock_publisher.publish.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_task_resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_ack_called_first():
    """ack() must be the very first await in handle_task_resolve."""
    call_log: list[str] = []

    async def tracking_ack():
        call_log.append("ack")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(True))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_client.chat_update = AsyncMock(side_effect=lambda **kw: call_log.append("chat_update"))

    mock_publisher = AsyncMock()

    from src.bolt_app import handle_task_resolve, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    await handle_task_resolve(
        ack=tracking_ack,
        body=_make_body("task_resolve"),
        client=mock_client,
    )

    assert call_log[0] == "ack", f"ack() was not first; order was {call_log}"


@pytest.mark.asyncio
async def test_resolve_publishes_task_completed_event():
    """handle_task_resolve publishes a task.completed event with required payload fields."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(True))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_publisher = AsyncMock()

    from src.bolt_app import handle_task_resolve, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    task_id = "task-xyz789"

    await handle_task_resolve(
        ack=AsyncMock(),
        body=_make_body("task_resolve", task_id=task_id),
        client=mock_client,
    )

    mock_publisher.publish.assert_awaited_once()
    publish_call = mock_publisher.publish.call_args
    topic = publish_call.args[0] if publish_call.args else publish_call.kwargs.get("topic")
    event = publish_call.args[1] if len(publish_call.args) > 1 else publish_call.kwargs.get("event")

    assert topic == "ocean.tasks"
    assert event["event_type"] == "task.completed"
    assert event["payload"]["task_id"] == task_id
    assert "actor_id" in event["payload"]
    assert "timestamp" in event


@pytest.mark.asyncio
async def test_resolve_calls_chat_update():
    """handle_task_resolve calls chat_update with resolved_card after publishing event."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result(True))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_client = AsyncMock()
    mock_publisher = AsyncMock()

    from src.bolt_app import handle_task_resolve, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    await handle_task_resolve(
        ack=AsyncMock(),
        body=_make_body("task_resolve"),
        client=mock_client,
    )

    mock_client.chat_update.assert_awaited_once()
