"""OUTC-07: ocean-events includes OutcomeRecorded class and new EventType literals.

Requirement: ocean-events library exports OutcomeRecorded with normalized fields
and EventType includes task.escalated, ticket.escalated.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

TYPES_PATH = pathlib.Path(__file__).resolve().parents[2] / "libs" / "ocean-events" / "src" / "ocean_events" / "types.py"
OUTCOMES_HANDLER_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "services" / "control-plane" / "src" / "handlers" / "outcomes.py"
)


def test_outcome_recorded_class_exists():
    """OutcomeRecorded dataclass exists in ocean_events.types."""
    source = TYPES_PATH.read_text()
    tree = ast.parse(source)
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "OutcomeRecorded" in class_names, "OutcomeRecorded class not found in types.py"


def test_outcome_recorded_has_required_fields():
    """OutcomeRecorded has entity_type, entity_id, resolution_type, resolved_by, correlation_id."""
    source = TYPES_PATH.read_text()
    required_fields = ["entity_type", "entity_id", "resolution_type", "resolved_by", "correlation_id"]
    for field in required_fields:
        assert field in source, f"Field '{field}' not found in OutcomeRecorded"


def test_event_type_includes_task_escalated():
    """EventType literal includes 'task.escalated'."""
    source = TYPES_PATH.read_text()
    assert '"task.escalated"' in source, "task.escalated not in EventType"


def test_event_type_includes_ticket_escalated():
    """EventType literal includes 'ticket.escalated'."""
    source = TYPES_PATH.read_text()
    assert '"ticket.escalated"' in source, "ticket.escalated not in EventType"


def test_resolution_type_literal_exists():
    """ResolutionType Literal is defined in types.py."""
    source = TYPES_PATH.read_text()
    assert "ResolutionType" in source, "ResolutionType not found in types.py"
    assert '"resolved"' in source
    assert '"false_positive"' in source
    assert '"completed"' in source
    assert '"missed"' in source


def test_build_outcome_event_exists():
    """build_outcome_event function exists in outcomes handler."""
    source = OUTCOMES_HANDLER_PATH.read_text()
    assert "def build_outcome_event(" in source


def test_build_outcome_event_returns_correct_structure():
    """build_outcome_event returns dict with event_type, source_system, payload fields."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("outcomes", OUTCOMES_HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.build_outcome_event(
        entity_type="task",
        entity_id="test-task-123",
        resolution_type="resolved",
        resolved_by="user-1",
        correlation_id="corr-abc",
    )
    assert result["event_type"] == "outcome.recorded"
    assert result["source_system"] == "control-plane"
    assert result["entity_type"] == "outcome"
    assert result["payload"]["entity_type"] == "task"
    assert result["payload"]["entity_id"] == "test-task-123"
    assert result["payload"]["resolution_type"] == "resolved"
    assert result["payload"]["resolved_by"] == "user-1"
    assert result["payload"]["resolved_at"] is not None
    assert result["correlation_id"] == "corr-abc"


def test_build_outcome_event_deterministic_entity_id():
    """build_outcome_event generates deterministic entity_id via uuid5."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("outcomes", OUTCOMES_HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result1 = mod.build_outcome_event(
        entity_type="task",
        entity_id="task-abc",
        resolution_type="resolved",
        resolved_by="user-1",
        correlation_id="corr-1",
    )
    result2 = mod.build_outcome_event(
        entity_type="task",
        entity_id="task-abc",
        resolution_type="resolved",
        resolved_by="user-1",
        correlation_id="corr-1",
    )
    # entity_id (outcome_id) should be deterministic
    assert result1["entity_id"] == result2["entity_id"]
    # But event_id should be unique (uuid4)
    assert result1["event_id"] != result2["event_id"]
    # Verify it matches expected uuid5
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "outcome-task-abc-resolved"))
    assert result1["entity_id"] == expected
