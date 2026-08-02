"""ESC-01: Escalation poller finds unclaimed tasks/tickets past threshold.

Verifies find_escalation_candidates returns items where
(now - check_time).total_seconds() > threshold for their priority.
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
    """Set escalation timeout env vars to known values for deterministic tests."""
    monkeypatch.setenv("ESCALATION_TIMEOUT_CRITICAL", "300")
    monkeypatch.setenv("ESCALATION_TIMEOUT_HIGH", "900")
    monkeypatch.setenv("ESCALATION_TIMEOUT_MEDIUM", "1800")
    monkeypatch.setenv("ESCALATION_TIMEOUT_LOW", "3600")


@pytest.mark.usefixtures("_patch_env")
async def test_find_candidates_returns_past_threshold_items():
    """Items past their priority threshold are returned as candidates."""
    mod = _load_escalation_module()
    find_escalation_candidates = mod.find_escalation_candidates

    now = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    # A "high" priority item created 20 min ago (threshold=900s=15min) -> past
    past_item = MagicMock()
    past_item._mapping = {
        "entity_type": "task",
        "entity_id": "task-001",
        "current_priority": "high",
        "created_at": now - timedelta(minutes=20),
        "escalated_at": None,
        "escalation_count": 0,
    }
    # Make attribute access work too
    past_item.current_priority = "high"
    past_item.escalated_at = None
    past_item.created_at = now - timedelta(minutes=20)

    # A "low" priority item created 30 min ago (threshold=3600s=60min) -> NOT past
    recent_item = MagicMock()
    recent_item._mapping = {
        "entity_type": "task",
        "entity_id": "task-002",
        "current_priority": "low",
        "created_at": now - timedelta(minutes=30),
        "escalated_at": None,
        "escalation_count": 0,
    }
    recent_item.current_priority = "low"
    recent_item.escalated_at = None
    recent_item.created_at = now - timedelta(minutes=30)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [past_item, recent_item]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    candidates = await find_escalation_candidates(session, now)

    assert len(candidates) == 1
    assert candidates[0]["entity_id"] == "task-001"


@pytest.mark.usefixtures("_patch_env")
async def test_find_candidates_uses_escalated_at_as_check_time():
    """Previously escalated items use escalated_at as the check time."""
    mod = _load_escalation_module()
    find_escalation_candidates = mod.find_escalation_candidates

    now = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    # Item escalated 10 min ago, current priority is "high" (threshold=900s=15min) -> NOT past
    item = MagicMock()
    item._mapping = {
        "entity_type": "task",
        "entity_id": "task-003",
        "current_priority": "high",
        "created_at": now - timedelta(hours=2),
        "escalated_at": now - timedelta(minutes=10),
        "escalation_count": 1,
    }
    item.current_priority = "high"
    item.escalated_at = now - timedelta(minutes=10)
    item.created_at = now - timedelta(hours=2)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [item]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    candidates = await find_escalation_candidates(session, now)
    assert len(candidates) == 0
