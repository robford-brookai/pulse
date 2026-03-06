"""Unit tests for control-plane routing rules."""
from __future__ import annotations

import sys
import os

# Allow importing src package from service root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src.rules import (
    FALLBACK_CHANNEL,
    FALLBACK_PRIORITY,
    channel_for,
    priority_for,
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
        # Routing rules are case-sensitive — "Glucose" != "glucose"
        assert channel_for("Glucose") == FALLBACK_CHANNEL

    def test_case_sensitive_mixed_misses(self):
        assert channel_for("BLOOD_PRESSURE") == FALLBACK_CHANNEL


class TestPriorityFor:
    def test_glucose_is_urgent(self):
        assert priority_for("glucose") == "urgent"

    def test_blood_pressure_is_urgent(self):
        assert priority_for("blood_pressure") == "urgent"

    def test_heart_rate_is_routine(self):
        assert priority_for("heart_rate") == "routine"

    def test_unknown_type_returns_routine(self):
        assert priority_for("unknown_xyz") == FALLBACK_PRIORITY

    def test_fallback_priority_is_routine(self):
        assert FALLBACK_PRIORITY == "routine"
