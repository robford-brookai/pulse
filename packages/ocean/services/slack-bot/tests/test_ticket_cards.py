"""Tests for ticket card Block Kit builders."""

from __future__ import annotations

from src.cards import (
    ticket_card,
    ticket_claimed_card,
    ticket_resolved_card,
    ticket_waiting_card,
)

TICKET_ID = "tkt-abc-123"
HUMAN_ID = "DEV-00042"
CATEGORY = "device_issue"
PRIORITY = "high"
DESCRIPTION = "Patient reports device not syncing data for 2 days."
AI_SUMMARY = "Device connectivity issue. Recommend replacement or firmware update."
PATIENT_ID = "patient-xyz"
CREATOR_ID = "U12345"


class TestTicketCardOpen:
    """ticket_card() with status='open'."""

    def test_header_contains_human_id(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
            patient_id=PATIENT_ID,
            creator_id=CREATOR_ID,
        )
        header = blocks[0]
        assert header["type"] == "header"
        assert HUMAN_ID in header["text"]["text"]

    def test_header_contains_green_circle_for_open(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
        )
        header_text = blocks[0]["text"]["text"]
        assert ":large_green_circle:" in header_text

    def test_fields_section_has_4_fields(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
            patient_id=PATIENT_ID,
            creator_id=CREATOR_ID,
        )
        section = blocks[1]
        assert section["type"] == "section"
        assert len(section["fields"]) == 4

    def test_fields_contain_category_and_priority(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
            patient_id=PATIENT_ID,
            creator_id=CREATOR_ID,
        )
        fields_text = " ".join(f["text"] for f in blocks[1]["fields"])
        assert "device_issue" in fields_text
        assert ":large_orange_circle:" in fields_text  # high priority emoji

    def test_description_block(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
        )
        # After fields section and divider, description section
        desc_block = blocks[3]
        assert desc_block["type"] == "section"
        assert DESCRIPTION in desc_block["text"]["text"]

    def test_ai_summary_block(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
        )
        ai_block = blocks[4]
        assert ai_block["type"] == "section"
        assert "*AI:*" in ai_block["text"]["text"]
        assert AI_SUMMARY in ai_block["text"]["text"]

    def test_open_has_3_action_buttons(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
        )
        actions = [b for b in blocks if b["type"] == "actions"]
        assert len(actions) == 1
        assert len(actions[0]["elements"]) == 3

    def test_open_action_ids(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
        )
        actions = [b for b in blocks if b["type"] == "actions"][0]
        action_ids = [el["action_id"] for el in actions["elements"]]
        assert "ticket_claim" in action_ids
        assert "ticket_resolve" in action_ids
        assert "ticket_wait" in action_ids

    def test_button_values_are_ticket_id(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "open",
            DESCRIPTION,
            AI_SUMMARY,
        )
        actions = [b for b in blocks if b["type"] == "actions"][0]
        for el in actions["elements"]:
            assert el["value"] == TICKET_ID


class TestTicketCardInProgress:
    """ticket_card() with status='in_progress'."""

    def test_header_contains_yellow_circle(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "in_progress",
            DESCRIPTION,
            AI_SUMMARY,
        )
        header_text = blocks[0]["text"]["text"]
        assert ":large_yellow_circle:" in header_text

    def test_in_progress_has_3_buttons_for_device_issue(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "in_progress",
            DESCRIPTION,
            AI_SUMMARY,
        )
        actions = [b for b in blocks if b["type"] == "actions"][0]
        # 2 base buttons + Create RMA for device_issue
        assert len(actions["elements"]) == 3

    def test_in_progress_action_ids(self):
        blocks = ticket_card(
            TICKET_ID,
            HUMAN_ID,
            CATEGORY,
            PRIORITY,
            "in_progress",
            DESCRIPTION,
            AI_SUMMARY,
        )
        actions = [b for b in blocks if b["type"] == "actions"][0]
        action_ids = [el["action_id"] for el in actions["elements"]]
        assert "ticket_resolve" in action_ids
        assert "ticket_wait" in action_ids
        assert "ticket_create_rma" in action_ids


class TestTicketClaimedCard:
    def test_header_yellow_circle_in_progress(self):
        blocks = ticket_claimed_card(TICKET_ID, HUMAN_ID, "U99999")
        header = blocks[0]
        assert ":large_yellow_circle:" in header["text"]["text"]
        assert "IN PROGRESS" in header["text"]["text"]

    def test_claimed_by_text(self):
        blocks = ticket_claimed_card(TICKET_ID, HUMAN_ID, "U99999")
        context = [b for b in blocks if b["type"] == "context"][0]
        context_text = " ".join(el.get("text", "") for el in context["elements"] if isinstance(el, dict))
        assert "<@U99999>" in context_text

    def test_has_resolve_and_wait_buttons(self):
        blocks = ticket_claimed_card(TICKET_ID, HUMAN_ID, "U99999")
        actions = [b for b in blocks if b["type"] == "actions"]
        assert len(actions) == 1
        action_ids = [el["action_id"] for el in actions[0]["elements"]]
        assert "ticket_resolve" in action_ids
        assert "ticket_wait" in action_ids


class TestTicketWaitingCard:
    def test_header_orange_circle_waiting(self):
        blocks = ticket_waiting_card(TICKET_ID, HUMAN_ID, "external_block")
        header = blocks[0]
        assert ":large_orange_circle:" in header["text"]["text"]
        assert "WAITING" in header["text"]["text"]

    def test_waiting_reason_displayed(self):
        blocks = ticket_waiting_card(TICKET_ID, HUMAN_ID, "external_block")
        context = [b for b in blocks if b["type"] == "context"][0]
        context_text = " ".join(el.get("text", "") for el in context["elements"] if isinstance(el, dict))
        assert "external_block" in context_text

    def test_has_resume_and_resolve_buttons(self):
        blocks = ticket_waiting_card(TICKET_ID, HUMAN_ID, "external_block")
        actions = [b for b in blocks if b["type"] == "actions"]
        assert len(actions) == 1
        action_ids = [el["action_id"] for el in actions[0]["elements"]]
        assert "ticket_resume" in action_ids
        assert "ticket_resolve" in action_ids


class TestTicketResolvedCard:
    def test_header_checkmark_resolved(self):
        blocks = ticket_resolved_card(TICKET_ID, HUMAN_ID, "U99999", "2h 15m")
        header = blocks[0]
        assert ":white_check_mark:" in header["text"]["text"]
        assert "RESOLVED" in header["text"]["text"]

    def test_resolved_by_text_with_duration(self):
        blocks = ticket_resolved_card(TICKET_ID, HUMAN_ID, "U99999", "2h 15m")
        context = [b for b in blocks if b["type"] == "context"][0]
        context_text = " ".join(el.get("text", "") for el in context["elements"] if isinstance(el, dict))
        assert "U99999" in context_text
        assert "2h 15m" in context_text

    def test_no_actions_block(self):
        blocks = ticket_resolved_card(TICKET_ID, HUMAN_ID, "U99999", "2h 15m")
        actions = [b for b in blocks if b.get("type") == "actions"]
        assert len(actions) == 0
