"""OUTC-06: Graph-projection consumes outcome.recorded and upserts outcomes table.

Verifies:
- handle_outcome_recorded upserts outcomes table with deterministic outcome_id
- outcome_type = "{entity_type}_{resolution_type}"
- interaction_id is NULL (nullable per migration 0014)
- graph-projection consumer.py EVENT_HANDLERS contains "outcome.recorded"
"""
from __future__ import annotations

import ast
import pathlib
import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

GRAPH_PROJ_ROOT = pathlib.Path(__file__).resolve().parents[2] / "services" / "graph-projection"
CONSUMER_PATH = GRAPH_PROJ_ROOT / "src" / "consumer.py"
HANDLER_PATH = GRAPH_PROJ_ROOT / "src" / "handlers" / "outcomes.py"

_OUTCOME_NS = uuid.NAMESPACE_URL


def _expected_outcome_id(entity_id: str, resolution_type: str) -> str:
    return str(uuid.uuid5(_OUTCOME_NS, f"outcome-{entity_id}-{resolution_type}"))


# ---------------------------------------------------------------------------
# Source inspection tests
# ---------------------------------------------------------------------------


class TestOutcomeRecordedSourceInspection:
    """OUTC-06: Verify graph-projection consumer registers outcome.recorded handler."""

    def test_consumer_has_outcome_recorded_handler(self):
        source = CONSUMER_PATH.read_text()
        tree = ast.parse(source)

        # Find the EVENT_HANDLERS dict (may be Assign or AnnAssign)
        handler_keys: list[str] = []
        for node in ast.walk(tree):
            dict_value = None
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "EVENT_HANDLERS":
                        dict_value = node.value
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "EVENT_HANDLERS":
                    dict_value = node.value

            if dict_value is not None and isinstance(dict_value, ast.Dict):
                for key in dict_value.keys:
                    if isinstance(key, ast.Constant):
                        handler_keys.append(key.value)

        assert "outcome.recorded" in handler_keys, (
            "EVENT_HANDLERS must contain 'outcome.recorded' key"
        )

    def test_handler_file_contains_handle_outcome_recorded(self):
        source = HANDLER_PATH.read_text()
        assert "async def handle_outcome_recorded(" in source


# ---------------------------------------------------------------------------
# Functional tests (mock session)
# ---------------------------------------------------------------------------


class TestHandleOutcomeRecorded:
    """OUTC-06: handle_outcome_recorded upserts outcomes table correctly."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        return session

    @pytest.mark.asyncio
    async def test_upserts_with_correct_outcome_type(self, mock_session):
        """outcome_type = '{entity_type}_{resolution_type}'."""
        # Lazy import to avoid dep tree until handler exists
        import sys
        sys.path.insert(0, str(GRAPH_PROJ_ROOT))
        from src.handlers.outcomes import handle_outcome_recorded

        event_data = {
            "event_id": "evt-001",
            "entity_id": "task-123",
            "event_type": "outcome.recorded",
            "payload": {
                "entity_type": "task",
                "entity_id": "task-123",
                "resolution_type": "resolved",
                "resolved_by": "user-1",
            },
        }

        await handle_outcome_recorded(event_data, mock_session)

        # Verify session.execute was called
        assert mock_session.execute.call_count == 1
        call_args = mock_session.execute.call_args
        params = call_args[1] if call_args[1] else call_args[0][1]
        assert params["outcome_type"] == "task_resolved"

    @pytest.mark.asyncio
    async def test_upserts_with_correct_outcome_id(self, mock_session):
        """outcome_id is deterministic via uuid5."""
        import sys
        sys.path.insert(0, str(GRAPH_PROJ_ROOT))
        from src.handlers.outcomes import handle_outcome_recorded

        event_data = {
            "event_id": "evt-002",
            "entity_id": "task-456",
            "event_type": "outcome.recorded",
            "payload": {
                "entity_type": "task",
                "entity_id": "task-456",
                "resolution_type": "completed",
                "resolved_by": "user-2",
            },
        }

        await handle_outcome_recorded(event_data, mock_session)

        call_args = mock_session.execute.call_args
        params = call_args[1] if call_args[1] else call_args[0][1]
        expected_id = _expected_outcome_id("task-456", "completed")
        assert params["outcome_id"] == expected_id

    @pytest.mark.asyncio
    async def test_interaction_id_is_null(self, mock_session):
        """interaction_id is NULL for task/ticket/alert outcomes (migration 0014)."""
        import sys
        sys.path.insert(0, str(GRAPH_PROJ_ROOT))
        from src.handlers.outcomes import handle_outcome_recorded

        event_data = {
            "event_id": "evt-003",
            "entity_id": "ticket-789",
            "event_type": "outcome.recorded",
            "payload": {
                "entity_type": "ticket",
                "entity_id": "ticket-789",
                "resolution_type": "resolved",
                "resolved_by": "user-3",
            },
        }

        await handle_outcome_recorded(event_data, mock_session)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "NULL" in sql_text, "SQL must use NULL for interaction_id"

    @pytest.mark.asyncio
    async def test_resolution_status_equals_resolution_type(self, mock_session):
        """resolution_status should be the raw resolution_type value."""
        import sys
        sys.path.insert(0, str(GRAPH_PROJ_ROOT))
        from src.handlers.outcomes import handle_outcome_recorded

        event_data = {
            "event_id": "evt-004",
            "entity_id": "alert-001",
            "event_type": "outcome.recorded",
            "payload": {
                "entity_type": "alert",
                "entity_id": "alert-001",
                "resolution_type": "false_positive",
                "resolved_by": "user-4",
            },
        }

        await handle_outcome_recorded(event_data, mock_session)

        call_args = mock_session.execute.call_args
        params = call_args[1] if call_args[1] else call_args[0][1]
        assert params["resolution_status"] == "false_positive"
