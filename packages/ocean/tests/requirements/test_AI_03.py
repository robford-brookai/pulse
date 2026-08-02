"""AI-03: Slack card uses "AI:" label, not emoji.

Requirement: The alert card AI summary block (block index 3) must use "*AI:*"
as its label — not a robot emoji or "AI Summary" text. The outreach draft card
section must use "AI: Outreach Draft" as its header.
"""
from __future__ import annotations

import pytest

from utils import setup_service

setup_service("slack-bot")

from src.cards import alert_card, outreach_draft_card  # noqa: E402


def test_alert_card_block_3_uses_ai_colon_label():
    """AI summary block uses '*AI:*' label — not emoji or alternate phrasing."""
    blocks = alert_card(
        task_id="task-001",
        patient_hash="sha256:abc",
        alert_type="glucose_high",
        severity="URGENT",
        timestamp="2026-03-06T07:00:00Z",
        ai_summary="Elevated glucose. Coordinate care.",
        hasura_url="http://hasura:8080",
        cited_signals=["glucose"],
    )

    ai_block = blocks[3]
    assert ai_block["type"] == "section"
    text = ai_block["text"]["text"]
    assert "AI:" in text, f"Expected 'AI:' label in: {text}"


def test_alert_card_block_3_no_robot_emoji():
    """AI summary block must NOT contain a robot emoji."""
    blocks = alert_card(
        task_id="task-002",
        patient_hash="sha256:def",
        alert_type="spo2_low",
        severity="CRITICAL",
        timestamp="2026-03-06T08:00:00Z",
        ai_summary="Low SpO2 detected.",
        hasura_url="http://hasura:8080",
        cited_signals=["spo2"],
    )

    ai_block = blocks[3]
    text = ai_block["text"]["text"]
    assert "\U0001f916" not in text, "Robot emoji found in AI summary block"
    assert "🤖" not in text


def test_alert_card_block_3_no_ai_summary_label():
    """AI summary block must NOT use the old 'AI Summary:' phrasing."""
    blocks = alert_card(
        task_id="task-003",
        patient_hash="sha256:ghi",
        alert_type="weight_drop",
        severity="HIGH",
        timestamp="2026-03-06T09:00:00Z",
        ai_summary="Weight dropped rapidly.",
        hasura_url="http://hasura:8080",
        cited_signals=["weight"],
    )

    ai_block = blocks[3]
    text = ai_block["text"]["text"]
    assert "AI Summary" not in text, "Old 'AI Summary' label found in AI block"


def test_outreach_draft_card_uses_ai_outreach_draft_label():
    """Outreach draft card section uses 'AI: Outreach Draft' header text."""
    blocks = outreach_draft_card(
        task_id="task-abc",
        draft_id="draft-xyz",
        draft_text="Calling to check on your glucose levels.",
    )

    section_blocks = [b for b in blocks if b.get("type") == "section"]
    assert any(
        "AI: Outreach Draft" in b.get("text", {}).get("text", "")
        for b in section_blocks
    ), "No section block with 'AI: Outreach Draft' text found"


def test_outreach_draft_card_has_approve_and_reject_actions():
    """Outreach draft card includes Approve + Reject action buttons."""
    blocks = outreach_draft_card(
        task_id="task-abc",
        draft_id="draft-xyz",
        draft_text="Calling to check in.",
    )

    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1

    action_ids = [el["action_id"] for el in action_blocks[0]["elements"]]
    assert "outreach_approve" in action_ids
    assert "outreach_reject" in action_ids
