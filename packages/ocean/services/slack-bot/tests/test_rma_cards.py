"""Tests for RMA-related card rendering in slack-bot."""
from __future__ import annotations

from src.cards import (
    _ticket_action_buttons,
    ticket_card,
    ticket_claimed_card,
)


TICKET_ID = "tkt-rma-001"
HUMAN_ID = "DEV-00042"
CATEGORY = "device_issue"
PRIORITY = "high"
DESCRIPTION = "Device not syncing"
AI_SUMMARY = "Likely connectivity issue"
PATIENT_ID = "pat-001"


class TestCreateRmaButton:
    """Create RMA button appears only on in_progress + device_issue."""

    def test_in_progress_device_issue_has_create_rma(self):
        elements = _ticket_action_buttons(TICKET_ID, "in_progress", category="device_issue")
        action_ids = [el["action_id"] for el in elements]
        assert "ticket_create_rma" in action_ids

    def test_in_progress_clinical_no_create_rma(self):
        elements = _ticket_action_buttons(TICKET_ID, "in_progress", category="clinical_support")
        action_ids = [el["action_id"] for el in elements]
        assert "ticket_create_rma" not in action_ids

    def test_open_device_issue_no_create_rma(self):
        elements = _ticket_action_buttons(TICKET_ID, "open", category="device_issue")
        action_ids = [el["action_id"] for el in elements]
        assert "ticket_create_rma" not in action_ids

    def test_waiting_device_issue_no_create_rma(self):
        elements = _ticket_action_buttons(TICKET_ID, "waiting", category="device_issue")
        action_ids = [el["action_id"] for el in elements]
        assert "ticket_create_rma" not in action_ids

    def test_create_rma_button_style_primary(self):
        elements = _ticket_action_buttons(TICKET_ID, "in_progress", category="device_issue")
        rma_btn = [el for el in elements if el["action_id"] == "ticket_create_rma"][0]
        assert rma_btn["style"] == "primary"


class TestRmaBadgeOnCard:
    """[RMA] badge and RMA status field on ticket cards."""

    def test_ticket_card_rma_badge_in_header(self):
        blocks = ticket_card(
            TICKET_ID, HUMAN_ID, CATEGORY, PRIORITY, "in_progress",
            DESCRIPTION, AI_SUMMARY, patient_id=PATIENT_ID,
            rma_return_id="ret-001",
        )
        header_text = blocks[0]["text"]["text"]
        assert "[RMA]" in header_text
        assert HUMAN_ID in header_text

    def test_ticket_card_no_rma_badge_without_return_id(self):
        blocks = ticket_card(
            TICKET_ID, HUMAN_ID, CATEGORY, PRIORITY, "in_progress",
            DESCRIPTION, AI_SUMMARY, patient_id=PATIENT_ID,
        )
        header_text = blocks[0]["text"]["text"]
        assert "[RMA]" not in header_text

    def test_ticket_card_rma_status_field(self):
        blocks = ticket_card(
            TICKET_ID, HUMAN_ID, CATEGORY, PRIORITY, "in_progress",
            DESCRIPTION, AI_SUMMARY, patient_id=PATIENT_ID,
            rma_status="shipped",
        )
        fields_section = blocks[1]
        fields_text = " ".join(f["text"] for f in fields_section["fields"])
        assert "RMA" in fields_text
        assert "shipped" in fields_text

    def test_ticket_card_no_rma_status_without_param(self):
        blocks = ticket_card(
            TICKET_ID, HUMAN_ID, CATEGORY, PRIORITY, "in_progress",
            DESCRIPTION, AI_SUMMARY, patient_id=PATIENT_ID,
        )
        fields_section = blocks[1]
        # Standard 4 fields only
        assert len(fields_section["fields"]) == 4

    def test_claimed_card_rma_badge(self):
        blocks = ticket_claimed_card(
            TICKET_ID, HUMAN_ID, "U99999",
            rma_return_id="ret-001",
        )
        header_text = blocks[0]["text"]["text"]
        assert "[RMA]" in header_text
