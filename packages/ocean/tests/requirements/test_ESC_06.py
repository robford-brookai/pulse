"""ESC-06: Escalation skips claimed/resolved items.

Verifies check_and_escalate removes escalation state and does not
publish for items with status in ("claimed", "completed", "resolved", "canceled").
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

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
@pytest.mark.parametrize("status", ["claimed", "completed", "resolved", "canceled"])
async def test_check_and_escalate_skips_terminal_status(status):
    """Items with terminal status are skipped and their escalation state is removed."""
    import importlib
    import src.escalation as esc_mod
    importlib.reload(esc_mod)
    from src.escalation import check_and_escalate

    created_at = datetime.now(tz=UTC) - timedelta(hours=2)

    candidate_row = MagicMock()
    candidate_row._mapping = {
        "entity_type": "task",
        "entity_id": "task-999",
        "current_priority": "high",
        "created_at": created_at,
        "escalated_at": None,
        "escalation_count": 0,
    }
    candidate_row.current_priority = "high"
    candidate_row.escalated_at = None
    candidate_row.created_at = created_at

    find_result = MagicMock()
    find_result.fetchall.return_value = [candidate_row]

    # Status check returns a terminal status
    status_result = MagicMock()
    status_result.scalar_one_or_none.return_value = status

    # remove_escalation_state execute
    remove_result = MagicMock()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[find_result, status_result, remove_result])

    publisher = AsyncMock()

    count = await check_and_escalate(session, publisher)

    assert count == 0
    publisher.publish.assert_not_called()


@pytest.mark.usefixtures("_patch_env")
async def test_check_and_escalate_processes_open_items():
    """Items with status 'open' ARE escalated (not skipped)."""
    import importlib
    import src.escalation as esc_mod
    importlib.reload(esc_mod)
    from src.escalation import check_and_escalate

    created_at = datetime.now(tz=UTC) - timedelta(hours=3)

    candidate_row = MagicMock()
    candidate_row._mapping = {
        "entity_type": "task",
        "entity_id": "task-open",
        "current_priority": "low",
        "created_at": created_at,
        "escalated_at": None,
        "escalation_count": 0,
    }
    candidate_row.current_priority = "low"
    candidate_row.escalated_at = None
    candidate_row.created_at = created_at

    find_result = MagicMock()
    find_result.fetchall.return_value = [candidate_row]

    status_result = MagicMock()
    status_result.scalar_one_or_none.return_value = "open"

    update_result = MagicMock()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[find_result, status_result, update_result])

    publisher = AsyncMock()

    count = await check_and_escalate(session, publisher)

    assert count == 1
    publisher.publish.assert_called_once()
