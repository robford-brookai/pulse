"""Source-inspection tests for graph-projection outcome consumer.

Verifies the outcome handler and EVENT_HANDLERS registration in
graph-projection without importing service modules.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDLER_SOURCE = REPO_ROOT / "services" / "graph-projection" / "src" / "handlers" / "outcomes.py"
CONSUMER_SOURCE = REPO_ROOT / "services" / "graph-projection" / "src" / "consumer.py"


def test_handler_file_exists():
    assert HANDLER_SOURCE.exists(), f"Expected handler at {HANDLER_SOURCE}"


def test_consumer_file_exists():
    assert CONSUMER_SOURCE.exists(), f"Expected consumer at {CONSUMER_SOURCE}"


def test_handle_outcome_recorded_signature():
    src = HANDLER_SOURCE.read_text()
    assert "async def handle_outcome_recorded(" in src


def test_outcome_recorded_in_consumer_source():
    src = CONSUMER_SOURCE.read_text()
    assert '"outcome.recorded"' in src, (
        "consumer.py must register outcome.recorded in EVENT_HANDLERS"
    )


def test_event_handlers_contains_outcome_recorded():
    """Parse consumer.py AST and verify EVENT_HANDLERS dict has outcome.recorded key."""
    src = CONSUMER_SOURCE.read_text()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        # Handle both `X = {}` (Assign) and `X: dict = {}` (AnnAssign)
        target_name = None
        value = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EVENT_HANDLERS":
                    target_name = target.id
                    value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "EVENT_HANDLERS":
                target_name = node.target.id
                value = node.value

        if target_name and isinstance(value, ast.Dict):
            keys = [
                k.value
                for k in value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            ]
            assert "outcome.recorded" in keys, (
                "EVENT_HANDLERS dict must contain 'outcome.recorded' key"
            )
            return

    raise AssertionError("EVENT_HANDLERS dict not found in consumer.py")
