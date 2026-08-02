"""Source-inspection tests for slack-bot escalation event handlers.

Verifies services/slack-bot/src/consumer.py contains the escalation
handler functions and EVENT_HANDLERS registrations.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "slack-bot" / "src" / "consumer.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected source file at {SOURCE}"


def test_handle_task_escalated_signature():
    src = _source()
    assert "async def handle_task_escalated(" in src


def test_handle_ticket_escalated_signature():
    src = _source()
    assert "async def handle_ticket_escalated(" in src


def test_task_escalated_in_event_handlers():
    src = _source()
    assert '"task.escalated"' in src, (
        "consumer.py EVENT_HANDLERS must contain task.escalated"
    )


def test_ticket_escalated_in_event_handlers():
    src = _source()
    assert '"ticket.escalated"' in src, (
        "consumer.py EVENT_HANDLERS must contain ticket.escalated"
    )


def test_ocean_critical_channel_routing():
    """Escalation handlers route UNCLAIMED CRITICAL to #ocean-critical."""
    src = _source()
    assert "ocean-critical" in src, (
        "consumer.py must route unclaimed critical items to ocean-critical channel"
    )
