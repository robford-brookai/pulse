"""Unit tests for delivery card builder functions."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src.cards import delivery_card, delivery_claimed_card


class TestDeliveryCard:
    """delivery_card renders Block Kit blocks for delivery notifications."""

    def test_block_count(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            days_since_consent=14,
            shipping_option="standard",
            tracking_numbers=["TRACK123"],
            active_alerts_count=2,
            device_history_count=1,
        )
        assert len(blocks) == 6  # header, section, divider, alerts section, divider, actions

    def test_header_contains_device_type(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            days_since_consent=14,
            shipping_option="standard",
            tracking_numbers=["TRACK123"],
            active_alerts_count=0,
            device_history_count=1,
        )
        header = blocks[0]
        assert header["type"] == "header"
        assert "BP Monitor" in header["text"]["text"]
        assert "Device Delivered" in header["text"]["text"]

    def test_fields_section(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            days_since_consent=14,
            shipping_option="express",
            tracking_numbers=["TRACK123", "TRACK456"],
            active_alerts_count=3,
            device_history_count=1,
        )
        fields_section = blocks[1]
        assert fields_section["type"] == "section"
        fields = fields_section["fields"]
        assert len(fields) == 4

        # Patient field
        assert "`pat-001`" in fields[0]["text"]
        # Days since consent
        assert "14 days" in fields[1]["text"]
        # Shipping
        assert "express" in fields[2]["text"]
        assert "TRACK123" in fields[2]["text"]
        # Device history - first device
        assert "First device" in fields[3]["text"]

    def test_replacement_device_label(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            days_since_consent=7,
            shipping_option="standard",
            tracking_numbers=[],
            active_alerts_count=0,
            device_history_count=3,
        )
        fields = blocks[1]["fields"]
        assert "Replacement" in fields[3]["text"]
        assert "3 total" in fields[3]["text"]

    def test_active_alerts_section(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            days_since_consent=7,
            shipping_option="standard",
            tracking_numbers=[],
            active_alerts_count=5,
            device_history_count=1,
        )
        alerts_section = blocks[3]
        assert alerts_section["type"] == "section"
        assert "5" in alerts_section["text"]["text"]

    def test_action_buttons(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            days_since_consent=7,
            shipping_option="standard",
            tracking_numbers=[],
            active_alerts_count=0,
            device_history_count=1,
        )
        actions = blocks[5]
        assert actions["type"] == "actions"
        elements = actions["elements"]
        assert len(elements) == 2

        claim_btn = elements[0]
        assert claim_btn["action_id"] == "delivery_claim"
        assert claim_btn["value"] == "ord-001"
        assert claim_btn["style"] == "primary"

        resolve_btn = elements[1]
        assert resolve_btn["action_id"] == "delivery_resolve"
        assert resolve_btn["value"] == "ord-001"

    def test_no_tracking_numbers(self):
        blocks = delivery_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="Scale",
            days_since_consent=3,
            shipping_option="overnight",
            tracking_numbers=[],
            active_alerts_count=0,
            device_history_count=1,
        )
        shipping_field = blocks[1]["fields"][2]
        assert "overnight" in shipping_field["text"]


class TestDeliveryClaimedCard:
    """delivery_claimed_card renders a claimed state for delivery handoff."""

    def test_header_shows_claimed(self):
        blocks = delivery_claimed_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            actor_id="U123ABC",
        )
        header = blocks[0]
        assert "CLAIMED" in header["text"]["text"]

    def test_shows_actor(self):
        blocks = delivery_claimed_card(
            order_id="ord-001",
            patient_id="pat-001",
            device_type="BP Monitor",
            actor_id="U123ABC",
        )
        context = blocks[1]
        assert "U123ABC" in context["elements"][0]["text"]
