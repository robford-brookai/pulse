"""Tests for graph_search — N-hop neighborhood traversal."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from src.graph_search import get_entity_neighborhood


def _make_row(**kwargs):
    """Build a mock SQLAlchemy row with _mapping."""
    row = MagicMock()
    row._mapping = kwargs
    return row


def _make_result(*rows):
    """Build a mock execute() result."""
    result = MagicMock()
    result.fetchone = MagicMock(return_value=rows[0] if rows else None)
    result.fetchall = MagicMock(return_value=list(rows))
    return result


@pytest.mark.asyncio
async def test_unknown_entity_returns_unknown_type():
    """Non-existent entity_id returns entity_type='unknown'."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_result())  # All tables return None

    result = await get_entity_neighborhood(session, "nonexistent-id", hops=1)
    assert result["entity_type"] == "unknown"
    assert result["root"] is None


@pytest.mark.asyncio
async def test_alert_entity_found():
    """Entity found in alerts table returns entity_type='alert'."""
    alert_row = _make_row(
        alert_id="alert-001",
        patient_id="patient-001",
        alert_type="glucose_high",
        severity="URGENT",
        status="open",
    )

    call_count = [0]

    async def mock_execute(stmt, params=None):
        call_count[0] += 1
        sql = str(stmt)
        if "alerts" in sql and call_count[0] == 1:
            # First call: checking patients table → not found
            return _make_result()
        if "alerts" in sql and call_count[0] == 2:
            # Second call: checking alerts table → found
            return _make_result(alert_row)
        # All subsequent calls return empty
        return _make_result()

    session = AsyncMock()
    session.execute = mock_execute

    result = await get_entity_neighborhood(session, "alert-001", hops=1)
    assert result["entity_type"] == "alert"
    assert result["root"]["alert_id"] == "alert-001"


@pytest.mark.asyncio
async def test_hops_0_returns_root_only():
    """hops=0 returns root entity only without traversal."""
    patient_row = _make_row(
        patient_id="patient-001",
        clinic_id="clinic-1",
        enrollment_status="active",
    )

    async def mock_execute(stmt, params=None):
        sql = str(stmt)
        if "patients" in sql and "patient_id" in sql:
            return _make_result(patient_row)
        return _make_result()

    session = AsyncMock()
    session.execute = mock_execute

    result = await get_entity_neighborhood(session, "patient-001", hops=0)
    assert result["root"]["patient_id"] == "patient-001"
    assert result["related"] == {}


@pytest.mark.asyncio
async def test_hops_2_includes_alerts_tasks_interactions():
    """hops=2 traversal includes alerts, tasks, and interactions."""
    patient_row = _make_row(
        patient_id="pt-001",
        clinic_id="c-1",
        enrollment_status="active",
    )
    alert_row = _make_row(alert_id="a-1", patient_id="pt-001", alert_type="g", severity="H", status="open")
    task_row = _make_row(task_id="t-1", patient_id="pt-001", task_type="outreach", priority="high", status="open")
    interaction_row = _make_row(interaction_id="i-1", patient_id="pt-001", interaction_type="call", outcome="completed")

    call_num = [0]

    async def mock_execute(stmt, params=None):
        sql = str(stmt)
        call_num[0] += 1
        if "patients" in sql and call_num[0] == 1:
            return _make_result(patient_row)
        if "alerts" in sql and "patient_id" in sql:
            return _make_result(alert_row)
        if "tasks" in sql and "patient_id" in sql:
            return _make_result(task_row)
        if "interactions" in sql and "patient_id" in sql:
            return _make_result(interaction_row)
        return _make_result()

    session = AsyncMock()
    session.execute = mock_execute

    result = await get_entity_neighborhood(session, "pt-001", hops=2)
    assert result["entity_type"] == "patient"
    assert "alerts" in result["related"]
    assert "tasks" in result["related"]
    assert "interactions" in result["related"]
