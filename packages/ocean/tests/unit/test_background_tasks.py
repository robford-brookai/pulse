"""Background task registration: event-store consumer and slack-bot lifespan.

Sourced from test/cat7_background_jobs.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import setup_service


@pytest.mark.asyncio
async def test_event_store_startup_creates_consumer_task(monkeypatch):
    """event-store lifespan creates a consumer asyncio task."""
    setup_service("event-store")

    from src import consumer  # noqa: PLC0415
    created_tasks = []

    original_create_task = asyncio.create_task

    def capture_create_task(coro, **kwargs):
        task = original_create_task(coro, **kwargs)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("asyncio.create_task", capture_create_task)

    run_consumer_called = []

    async def fake_run_consumer(writer, brokers):
        run_consumer_called.append(brokers)
        await asyncio.sleep(999)

    monkeypatch.setattr(consumer, "run_consumer", fake_run_consumer)
    monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")

    from src.main import startup  # noqa: PLC0415

    startup_task = asyncio.create_task(startup())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # second yield lets inner consumer task start
    startup_task.cancel()
    for t in created_tasks:
        t.cancel()

    assert len(run_consumer_called) >= 1


@pytest.mark.asyncio
async def test_slack_bot_skips_consumers_without_token(monkeypatch):
    """When SLACK_BOT_TOKEN is empty, slack-bot yields without starting tasks."""
    setup_service("slack-bot")

    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_URL", "")

    import importlib  # noqa: PLC0415
    import src.main as slack_main  # noqa: PLC0415
    importlib.reload(slack_main)

    tasks_created = []
    original_create_task = asyncio.create_task

    def capture(coro, **kwargs):
        task = original_create_task(coro, **kwargs)
        tasks_created.append(task)
        return task

    with patch("asyncio.create_task", side_effect=capture):
        app_mock = MagicMock()
        async with slack_main.lifespan(app_mock):
            pass

    assert len(tasks_created) == 0
