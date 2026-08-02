"""Unit tests for control-plane routing rules."""

from __future__ import annotations

import os
import sys

# Allow importing src package from service root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from src.rules import (
    FALLBACK_CHANNEL,
    FALLBACK_PRIORITY,
    FALLBACK_TICKET_CHANNEL,
    channel_for,
    is_valid_transition,
    priority_for,
    ticket_channel_for,
    ticket_priority_channels,
)


class TestChannelFor:
    def test_known_glucose(self):
        assert channel_for("glucose") == "#care-alerts-glucose"

    def test_known_blood_pressure(self):
        assert channel_for("blood_pressure") == "#care-alerts-bp"

    def test_known_heart_rate(self):
        assert channel_for("heart_rate") == "#care-alerts-hr"

    def test_known_weight(self):
        assert channel_for("weight") == "#care-alerts-weight"

    def test_known_medication(self):
        assert channel_for("medication") == "#care-alerts-medication"

    def test_unknown_type_returns_fallback(self):
        assert channel_for("unknown_xyz") == FALLBACK_CHANNEL

    def test_empty_string_returns_fallback(self):
        assert channel_for("") == FALLBACK_CHANNEL

    def test_case_sensitive_uppercase_misses(self):
        assert channel_for("Glucose") == FALLBACK_CHANNEL

    def test_case_sensitive_mixed_misses(self):
        assert channel_for("BLOOD_PRESSURE") == FALLBACK_CHANNEL


class TestPriorityFor:
    def test_glucose_is_critical(self):
        assert priority_for("glucose") == "critical"

    def test_blood_pressure_is_critical(self):
        assert priority_for("blood_pressure") == "critical"

    def test_heart_rate_is_medium(self):
        assert priority_for("heart_rate") == "medium"

    def test_unknown_type_returns_medium(self):
        assert priority_for("unknown_xyz") == FALLBACK_PRIORITY

    def test_fallback_priority_is_medium(self):
        assert FALLBACK_PRIORITY == "medium"


class TestTicketChannelFor:
    def test_device_issue(self):
        assert ticket_channel_for("device_issue") == "#ocean-devices"

    def test_patient_activation(self):
        assert ticket_channel_for("patient_activation") == "#ocean-activation"

    def test_clinical_support(self):
        assert ticket_channel_for("clinical_support") == "#ocean-clinical"

    def test_engineering_it(self):
        assert ticket_channel_for("engineering_it") == "#ocean-engineering"

    def test_unknown_returns_fallback(self):
        assert ticket_channel_for("unknown") == FALLBACK_TICKET_CHANNEL

    def test_empty_returns_fallback(self):
        assert ticket_channel_for("") == FALLBACK_TICKET_CHANNEL


class TestTicketPriorityChannels:
    def test_critical_crosspost(self):
        assert ticket_priority_channels("critical") == ["#ocean-critical"]

    def test_high_crosspost(self):
        assert ticket_priority_channels("high") == ["#ocean-high"]

    def test_medium_no_crosspost(self):
        assert ticket_priority_channels("medium") == []

    def test_low_no_crosspost(self):
        assert ticket_priority_channels("low") == []

    def test_unknown_no_crosspost(self):
        assert ticket_priority_channels("unknown") == []


class TestIsValidTransition:
    def test_open_to_in_progress(self):
        assert is_valid_transition("open", "in_progress") is True

    def test_open_to_waiting(self):
        assert is_valid_transition("open", "waiting") is True

    def test_in_progress_to_waiting(self):
        assert is_valid_transition("in_progress", "waiting") is True

    def test_in_progress_to_resolved(self):
        assert is_valid_transition("in_progress", "resolved") is True

    def test_waiting_to_in_progress(self):
        assert is_valid_transition("waiting", "in_progress") is True

    def test_waiting_to_resolved(self):
        assert is_valid_transition("waiting", "resolved") is True

    def test_resolved_to_open_is_illegal(self):
        assert is_valid_transition("resolved", "open") is False

    def test_open_to_resolved_is_illegal(self):
        assert is_valid_transition("open", "resolved") is False

    def test_resolved_to_in_progress_is_illegal(self):
        assert is_valid_transition("resolved", "in_progress") is False

    def test_unknown_current_is_illegal(self):
        assert is_valid_transition("unknown", "open") is False
