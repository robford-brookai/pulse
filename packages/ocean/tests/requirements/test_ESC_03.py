"""ESC-03: Escalation state persisted in Postgres, rehydrated on startup.

Verifies insert_escalation_state writes a row, and rehydrate_and_catch_up
calls check_and_escalate to process items that timed out during downtime.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "services/control-plane")


@pytest.fixture
def _patch_env(monkeypatch):
    monkeypatch.setenv("ESCALATION_TIMEOUT_CRITICAL", "300")
    monkeypatch.setenv("ESCALATION_TIMEOUT_HIGH", "900")
    monkeypatch.setenv("ESCALATION_TIMEOUT_MEDIUM", "1800")
    monkeypatch.setenv("ESCALATION_TIMEOUT_LOW", "3600")
    monkeypatch.setenv("ESCALATION_ENABLED", "true")


@pytest.mark.usefixtures("_patch_env")
async def test_insert_escalation_state_executes_insert():
    """insert_escalation_state issues INSERT with correct parameters."""
    import importlib
    import src.escalation as esc_mod
    importlib.reload(esc_mod)
    from src.escalation import insert_escalation_state

    session = AsyncMock()
    now = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)

    await insert_escalation_state(session, "task", "task-001", "high", now)

    session.execute.assert_called_once()
    call_args = session.execute.call_args
    sql_text = str(call_args[0][0])
    params = call_args[0][1]

    assert "INSERT INTO task_escalation_state" in sql_text
    assert params["entity_type"] == "task"
    assert params["entity_id"] == "task-001"
    assert params["priority"] == "high"
    assert params["created_at"] == now


@pytest.mark.usefixtures("_patch_env")
async def test_rehydrate_and_catch_up_calls_check_and_escalate():
    """rehydrate_and_catch_up delegates to check_and_escalate."""
    import importlib
    import src.escalation as esc_mod
    importlib.reload(esc_mod)
    from src.escalation import rehydrate_and_catch_up

    session = AsyncMock()
    publisher = AsyncMock()

    with patch.object(esc_mod, "check_and_escalate", new_callable=AsyncMock, return_value=3) as mock_check:
        count = await rehydrate_and_catch_up(session, publisher)

    assert count == 3
    mock_check.assert_called_once_with(session, publisher)
