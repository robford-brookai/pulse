"""Source-inspection tests for escalation Block Kit cards.

Verifies services/slack-bot/src/cards.py contains escalation card
builders and the escalated parameter on alert_card and ticket_card.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "slack-bot" / "src" / "cards.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected source file at {SOURCE}"


def test_escalation_thread_reply_signature():
    src = _source()
    assert "def escalation_thread_reply(" in src


def test_unclaimed_critical_reply_signature():
    src = _source()
    assert "def unclaimed_critical_reply(" in src


def test_alert_card_escalated_parameter():
    """alert_card must accept an 'escalated' parameter."""
    src = _source()
    # Find the def alert_card( block and check escalated appears before the closing )
    match = re.search(r"def alert_card\([^)]+\)", src, re.DOTALL)
    assert match, "alert_card function not found"
    assert "escalated" in match.group(0), (
        "alert_card must accept 'escalated' parameter"
    )


def test_ticket_card_escalated_parameter():
    """ticket_card must accept an 'escalated' parameter."""
    src = _source()
    match = re.search(r"def ticket_card\([^)]+\)", src, re.DOTALL)
    assert match, "ticket_card function not found"
    assert "escalated" in match.group(0), (
        "ticket_card must accept 'escalated' parameter"
    )


def test_escalated_badge_text():
    src = _source()
    assert "[ESCALATED]" in src, "cards.py must contain [ESCALATED] badge text"
