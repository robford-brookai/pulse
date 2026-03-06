"""Tests for Slack Block Kit card builders."""
from __future__ import annotations

import pytest

from src.cards import alert_card, claimed_card, outreach_draft_card, resolved_card


TASK_ID = "task-abc-123"
PATIENT_HASH = "sha256:deadbeef"
ALERT_TYPE = "glucose_high"
SEVERITY = "URGENT"
TIMESTAMP = "2026-03-06T07:00:00Z"
AI_SUMMARY = "Patient has elevated glucose. Recommend immediate follow-up."
HASURA_URL = "http://hasura:8090/console/data/default/schema/public/tables/tasks"


def make_alert_card(cited_signals=None):
    return alert_card(
        task_id=TASK_ID,
        patient_hash=PATIENT_HASH,
        alert_type=ALERT_TYPE,
        severity=SEVERITY,
        timestamp=TIMESTAMP,
        ai_summary=AI_SUMMARY,
        hasura_url=HASURA_URL,
        cited_signals=cited_signals,
    )


class TestAlertCard:
    def test_returns_exactly_7_blocks(self):
        """Phase 4: alert_card has 7 blocks (added signals citation block)."""
        blocks = make_alert_card()
        assert len(blocks) == 7

    def test_header_contains_severity(self):
        blocks = make_alert_card()
        header = blocks[0]
        assert header["type"] == "header"
        assert SEVERITY in header["text"]["text"]

    def test_header_formats_alert_type_title_case(self):
        blocks = make_alert_card()
        header = blocks[0]
        # "glucose_high" -> "Glucose High"
        assert "Glucose High" in header["text"]["text"]

    def test_second_block_is_section_with_4_fields(self):
        blocks = make_alert_card()
        section = blocks[1]
        assert section["type"] == "section"
        assert "fields" in section
        assert len(section["fields"]) == 4

    def test_ai_summary_block_uses_ai_label(self):
        """Phase 4: block 3 uses 'AI:' label (not emoji)."""
        blocks = make_alert_card()
        ai_block = blocks[3]
        assert ai_block["type"] == "section"
        assert "*AI:*" in ai_block["text"]["text"]

    def test_ai_summary_block_contains_summary(self):
        blocks = make_alert_card()
        ai_block = blocks[3]
        assert AI_SUMMARY in ai_block["text"]["text"]

    def test_signals_block_at_position_4(self):
        """Phase 4: block 4 is the context signals citation."""
        blocks = make_alert_card(cited_signals=["glucose", "weight"])
        signals_block = blocks[4]
        assert signals_block["type"] == "section"
        assert "glucose" in signals_block["text"]["text"]
        assert "weight" in signals_block["text"]["text"]

    def test_signals_block_shows_none_when_empty(self):
        blocks = make_alert_card(cited_signals=[])
        signals_block = blocks[4]
        assert "none" in signals_block["text"]["text"]

    def test_dividers_at_positions_2_and_5(self):
        """Phase 4: dividers at positions 2 and 5 (signals citation at 4)."""
        blocks = make_alert_card()
        assert blocks[2]["type"] == "divider"
        assert blocks[5]["type"] == "divider"

    def test_actions_block_at_position_6(self):
        blocks = make_alert_card()
        actions = blocks[6]
        assert actions["type"] == "actions"
        assert actions["block_id"] == f"task_actions_{TASK_ID}"

    def test_actions_block_has_exactly_3_elements(self):
        blocks = make_alert_card()
        actions = blocks[6]
        assert len(actions["elements"]) == 3

    def test_action_ids_are_correct(self):
        blocks = make_alert_card()
        actions = blocks[6]
        action_ids = [el["action_id"] for el in actions["elements"]]
        assert "task_claim" in action_ids
        assert "task_resolve" in action_ids
        assert "task_view_context" in action_ids

    def test_task_claim_has_primary_style(self):
        blocks = make_alert_card()
        actions = blocks[6]
        claim = next(el for el in actions["elements"] if el["action_id"] == "task_claim")
        assert claim["style"] == "primary"

    def test_task_resolve_has_danger_style(self):
        blocks = make_alert_card()
        actions = blocks[6]
        resolve = next(el for el in actions["elements"] if el["action_id"] == "task_resolve")
        assert resolve["style"] == "danger"

    def test_view_context_has_url(self):
        blocks = make_alert_card()
        actions = blocks[6]
        view = next(el for el in actions["elements"] if el["action_id"] == "task_view_context")
        assert view["url"] == HASURA_URL


class TestOutreachDraftCard:
    def test_has_section_with_ai_label(self):
        blocks = outreach_draft_card(TASK_ID, "draft-123", "Follow up on glucose alert.")
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        assert any("AI: Outreach Draft" in b["text"]["text"] for b in section_blocks)

    def test_has_approve_and_reject_buttons(self):
        blocks = outreach_draft_card(TASK_ID, "draft-123", "Follow up on glucose alert.")
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 1
        action_ids = [el["action_id"] for el in action_blocks[0]["elements"]]
        assert "outreach_approve" in action_ids
        assert "outreach_reject" in action_ids

    def test_block_id_includes_draft_id(self):
        draft_id = "draft-xyz"
        blocks = outreach_draft_card(TASK_ID, draft_id, "Text.")
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert action_blocks[0]["block_id"] == f"outreach_actions_{draft_id}"


class TestClaimedCard:
    def test_returns_no_actions_block(self):
        blocks = claimed_card(task_id=TASK_ID, actor_id="user-xyz")
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 0

    def test_header_indicates_claimed(self):
        blocks = claimed_card(task_id=TASK_ID, actor_id="user-xyz")
        header = next(b for b in blocks if b.get("type") == "header")
        assert "CLAIMED" in header["text"]["text"]

    def test_body_includes_actor_id(self):
        actor_id = "user-xyz"
        blocks = claimed_card(task_id=TASK_ID, actor_id=actor_id)
        all_text = " ".join(
            b.get("text", {}).get("text", "")
            for b in blocks
            if b.get("type") == "section"
        )
        assert actor_id in all_text


class TestResolvedCard:
    def test_returns_no_actions_block(self):
        blocks = resolved_card(task_id=TASK_ID, actor_id="user-abc")
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 0

    def test_header_indicates_resolved(self):
        blocks = resolved_card(task_id=TASK_ID, actor_id="user-abc")
        header = next(b for b in blocks if b.get("type") == "header")
        assert "RESOLVED" in header["text"]["text"]

    def test_body_includes_actor_id(self):
        actor_id = "user-abc"
        blocks = resolved_card(task_id=TASK_ID, actor_id=actor_id)
        all_text = " ".join(
            b.get("text", {}).get("text", "")
            for b in blocks
            if b.get("type") == "section"
        )
        assert actor_id in all_text
