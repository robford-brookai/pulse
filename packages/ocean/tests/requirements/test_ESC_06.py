"""ESC-06: Escalation skips claimed/resolved items.

Verifies check_and_escalate removes escalation state and does not
publish for items with status in ("claimed", "completed", "resolved", "canceled").
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

CONTROL_PLANE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "control-plane"
ESCALATION_PATH = CONTROL_PLANE_ROOT / "src" / "escalation.py"


def _load_escalation_module() -> ModuleType:
    """Load escalation.py via importlib to avoid sys.path pollution."""
    saved = {}
    for key in list(sys.modules.keys()):
        if key == "src" or key.startswith("src."):
            saved[key] = sys.modules.pop(key)

    original_path = sys.path.copy()
    sys.path.insert(0, str(CONTROL_PLANE_ROOT))

    try:
        spec = importlib.util.spec_from_file_location(
            "control_plane_escalation",
            ESCALATION_PATH,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path = original_path
        for key in list(sys.modules.keys()):
            if key == "src" or key.startswith("src."):
                del sys.modules[key]
        sys.modules.update(saved)


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
    mod = _load_escalation_module()
    check_and_escalate = mod.check_and_escalate

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
    mod = _load_escalation_module()
    check_and_escalate = mod.check_and_escalate

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
