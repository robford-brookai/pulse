"""AI-02: Cited signals populated in alert card.

Requirement: The alert card Block Kit structure includes a signals citation block
(block index 4) that lists the signal types returned by the AI summary, shown as
"_Context signals: <signal1>, <signal2>_".
"""
from __future__ import annotations

import pytest

from utils import setup_service

setup_service("slack-bot")

from src.cards import alert_card  # noqa: E402


def test_alert_card_cited_signals_appear_in_block_4():
    """Block 4 of alert_card contains the cited signal type names."""
    blocks = alert_card(
        task_id="task-001",
        patient_hash="sha256:deadbeef",
        alert_type="glucose_high",
        severity="URGENT",
        timestamp="2026-03-06T07:00:00Z",
        ai_summary="Patient has elevated glucose.",
        hasura_url="http://hasura:8080",
        cited_signals=["glucose", "weight", "spo2"],
    )

    signals_block = blocks[4]
    assert signals_block["type"] == "section"
    text = signals_block["text"]["text"]
    assert "glucose" in text
    assert "weight" in text
    assert "spo2" in text


def test_alert_card_no_signals_shows_none():
    """When cited_signals is empty, block 4 shows 'none'."""
    blocks = alert_card(
        task_id="task-002",
        patient_hash="sha256:cafebabe",
        alert_type="weight_drop",
        severity="HIGH",
        timestamp="2026-03-06T08:00:00Z",
        ai_summary="Patient weight has dropped.",
        hasura_url="http://hasura:8080",
        cited_signals=[],
    )

    signals_block = blocks[4]
    text = signals_block["text"]["text"]
    assert "none" in text


def test_alert_card_none_signals_defaults_to_empty():
    """cited_signals=None is treated identically to []."""
    blocks = alert_card(
        task_id="task-003",
        patient_hash="sha256:feedface",
        alert_type="alert",
        severity="LOW",
        timestamp="2026-03-06T09:00:00Z",
        ai_summary="Summary.",
        hasura_url="http://hasura:8080",
        cited_signals=None,
    )

    signals_block = blocks[4]
    text = signals_block["text"]["text"]
    assert "none" in text


def test_alert_card_signals_block_is_italic_mrkdwn():
    """Signals citation uses mrkdwn with leading underscore for italics."""
    blocks = alert_card(
        task_id="task-004",
        patient_hash="sha256:abc",
        alert_type="test",
        severity="MED",
        timestamp="2026-03-06T10:00:00Z",
        ai_summary="Test.",
        hasura_url="http://hasura:8080",
        cited_signals=["glucose"],
    )

    signals_block = blocks[4]
    assert signals_block["text"]["type"] == "mrkdwn"
    # Should be wrapped in underscores for italic formatting
    text = signals_block["text"]["text"]
    assert text.startswith("_") and text.endswith("_")
