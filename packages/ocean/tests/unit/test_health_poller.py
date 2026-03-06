"""Health poller background job: silence detection and repeat-alert suppression.

Sourced from test/cat7_background_jobs.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import setup_service

setup_service("slack-bot")

from src.health_poller import poll_connector_health, SILENCE_THRESHOLD_SECS, REPEAT_INTERVAL_SECS  # noqa: E402


def test_silence_threshold_is_300_seconds():
    """Spec requires exactly 300s silence threshold."""
    assert SILENCE_THRESHOLD_SECS == 300


def test_repeat_interval_is_1800_seconds():
    """Spec requires exactly 1800s repeat interval."""
    assert REPEAT_INTERVAL_SECS == 1800


@pytest.mark.asyncio
async def test_poll_posts_alert_for_silent_connector():
    """Connector silent > 300s and never alerted triggers Slack post."""
    now = datetime.now(tz=timezone.utc)
    silent_row = MagicMock()
    silent_row.connector_id = "pocar-connector"
    silent_row.connector_name = "POCAR"
    silent_row.last_seen = now - timedelta(seconds=400)
    silent_row.last_alerted_at = None

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [silent_row]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_session_maker = MagicMock(return_value=mock_session)

    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock(return_value={"ok": True})

    call_count = 0

    async def fake_sleep(_n):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await poll_connector_health(slack_client, "#ocean-ops", mock_session_maker)

    slack_client.chat_postMessage.assert_called_once()
    call_kwargs = slack_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "#ocean-ops"
    assert "POCAR" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_poll_skips_recently_alerted_connector():
    """Connector alerted < 1800s ago is NOT re-alerted."""
    now = datetime.now(tz=timezone.utc)
    row = MagicMock()
    row.connector_id = "pocar-connector"
    row.connector_name = "POCAR"
    row.last_seen = now - timedelta(seconds=400)
    row.last_alerted_at = now - timedelta(seconds=60)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [row]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_maker = MagicMock(return_value=mock_session)
    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock()

    call_count = 0

    async def fake_sleep(_n):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await poll_connector_health(slack_client, "#ocean-ops", mock_session_maker)

    slack_client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
async def test_poll_does_not_crash_on_exception():
    """poll_connector_health catches exceptions and continues loop."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_maker = MagicMock(return_value=mock_session)
    slack_client = AsyncMock()

    call_count = 0

    async def fake_sleep(_n):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await poll_connector_health(slack_client, "#ocean-ops", mock_session_maker)

    # Made it through 2 loop iterations (exception swallowed each time)
    assert call_count == 3
    slack_client.chat_postMessage.assert_not_called()
