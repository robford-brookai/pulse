"""ALRT-01: Alert snooze infrastructure — snooze suppresses re-routing until expiry.

Source-inspection + unit tests following the test_SRCH_01.py pattern.
Verifies: migration DDL, event types, snooze button, bolt handlers,
control-plane snooze guard, and card builder outputs.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SLACK_BOT_ROOT = REPO_ROOT / "services" / "slack-bot"
CARDS_PATH = SLACK_BOT_ROOT / "src" / "cards.py"
BOLT_APP_PATH = SLACK_BOT_ROOT / "src" / "bolt_app.py"
TYPES_PATH = REPO_ROOT / "libs" / "ocean-events" / "src" / "ocean_events" / "types.py"
MIGRATION_PATH = REPO_ROOT / "infra" / "postgres" / "versions" / "0017_alert_snooze.py"
ALERTS_HANDLER_PATH = REPO_ROOT / "services" / "control-plane" / "src" / "handlers" / "alerts.py"


# ═══════════════════════════════════════════════════════════════════════════
# Source-inspection tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceInspection:
    """Verify that all ALRT-01 artifacts exist and contain expected strings."""

    def test_migration_0017_exists(self):
        assert MIGRATION_PATH.exists(), f"Missing {MIGRATION_PATH}"

    def test_migration_0017_creates_alert_snoozes_table(self):
        source = MIGRATION_PATH.read_text()
        assert "alert_snoozes" in source
        assert "snooze_until" in source

    def test_event_type_alert_snoozed(self):
        source = TYPES_PATH.read_text()
        assert '"alert.snoozed"' in source

    def test_event_type_alert_unsnoozed(self):
        source = TYPES_PATH.read_text()
        assert '"alert.unsnoozed"' in source

    def test_snooze_button_in_alert_card(self):
        source = CARDS_PATH.read_text()
        assert "task_snooze" in source

    def test_snooze_duration_card_defined(self):
        source = CARDS_PATH.read_text()
        assert "def snooze_duration_card" in source

    def test_snoozed_card_defined(self):
        source = CARDS_PATH.read_text()
        assert "def snoozed_card" in source

    def test_bolt_task_snooze_handler(self):
        source = BOLT_APP_PATH.read_text()
        assert '@bolt_app.action("task_snooze")' in source

    def test_bolt_snooze_confirm_handler(self):
        source = BOLT_APP_PATH.read_text()
        assert '@bolt_app.action("snooze_confirm")' in source

    def test_handle_alert_created_snooze_check(self):
        source = ALERTS_HANDLER_PATH.read_text()
        assert "alert_snoozes" in source


# ═══════════════════════════════════════════════════════════════════════════
# Import helper — load cards.py via spec_from_file_location
# ═══════════════════════════════════════════════════════════════════════════


def _import_cards():
    """Import cards module from source path, isolated from the rest of slack-bot."""
    service_dir = str(SLACK_BOT_ROOT)
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    keys_to_remove = [k for k in sys.modules if k.startswith("src.cards")]
    for k in keys_to_remove:
        del sys.modules[k]

    spec = importlib.util.spec_from_file_location("src.cards", CARDS_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["src.cards"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cards_module():
    return _import_cards()


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests — card builders
# ═══════════════════════════════════════════════════════════════════════════


class TestAlertCardSnoozeButton:
    """alert_card block 6 must contain a Snooze button with action_id task_snooze."""

    def test_alert_card_has_snooze_button(self, cards_module):
        blocks = cards_module.alert_card(
            task_id="task-001",
            patient_hash="abc123",
            alert_type="high_glucose",
            severity="critical",
            timestamp="2026-03-18T12:00:00Z",
            ai_summary="Glucose elevated",
            hasura_url="https://hasura.example.com",
        )
        actions_block = blocks[6]
        assert actions_block["type"] == "actions"
        action_ids = [el["action_id"] for el in actions_block["elements"]]
        assert "task_snooze" in action_ids


class TestSnoozeDurationCard:
    """snooze_duration_card must return a static_select with 5 preset options."""

    def test_snooze_duration_card_has_options(self, cards_module):
        blocks = cards_module.snooze_duration_card(task_id="task-001")
        assert len(blocks) >= 1
        accessory = blocks[0]["accessory"]
        assert accessory["type"] == "static_select"
        assert accessory["action_id"] == "snooze_confirm"
        options = accessory["options"]
        assert len(options) == 5
        # Verify all encode task_id
        for opt in options:
            assert opt["value"].startswith("task-001:")


class TestSnoozedCard:
    """snoozed_card must render confirmation text with who, how long, and note."""

    def test_snoozed_card_renders_confirmation(self, cards_module):
        blocks = cards_module.snoozed_card(
            task_id="task-001",
            duration="1 hour",
            snoozed_by="U123",
        )
        assert blocks[0]["type"] == "header"
        assert "SNOOZED" in blocks[0]["text"]["text"]
        body_text = blocks[1]["text"]["text"]
        assert "U123" in body_text
        assert "1 hour" in body_text
        assert "won't re-trigger" in body_text
