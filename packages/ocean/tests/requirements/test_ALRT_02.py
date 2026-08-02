"""ALRT-02: False-positive rate flagging for alert cards.

Source-inspection + unit tests verifying:
- Control-plane computes FP rate from resolved alerts
- FP rate included in task.created event payload
- alert_card accepts fp_rate param and renders warning when >= 0.3
- Consumer passes fp_rate through to alert_card
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERTS_PATH = REPO_ROOT / "services" / "control-plane" / "src" / "handlers" / "alerts.py"
CARDS_PATH = REPO_ROOT / "services" / "slack-bot" / "src" / "cards.py"
CONSUMER_PATH = REPO_ROOT / "services" / "slack-bot" / "src" / "consumer.py"


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


class TestSourceInspection:
    """Verify FP rate artifacts exist in the correct source files."""

    def test_fp_rate_in_handle_alert_created(self):
        """alerts.py must reference 'false_positive' for the FP rate query."""
        source = ALERTS_PATH.read_text()
        assert "false_positive" in source, "FP rate query missing from alerts.py"

    def test_fp_rate_in_task_created_payload(self):
        """alerts.py must include fp_rate in the task.created event payload."""
        source = ALERTS_PATH.read_text()
        assert '"fp_rate"' in source, "fp_rate not in task_event payload"

    def test_fp_rate_computation_log(self):
        """alerts.py must log fp_rate_computed for observability."""
        source = ALERTS_PATH.read_text()
        assert "fp_rate_computed" in source, "fp_rate_computed log missing"

    def test_alert_card_accepts_fp_rate(self):
        """cards.py alert_card must accept fp_rate parameter."""
        source = CARDS_PATH.read_text()
        assert "fp_rate" in source, "fp_rate param missing from cards.py"

    def test_consumer_passes_fp_rate(self):
        """consumer.py handle_task_created must extract and pass fp_rate."""
        source = CONSUMER_PATH.read_text()
        # Check that fp_rate is extracted from payload AND passed to alert_card
        assert "fp_rate" in source, "fp_rate missing from consumer.py"
        assert "fp_rate=fp_rate" in source, "fp_rate not passed to alert_card"

    def test_fp_rate_warning_threshold(self):
        """cards.py must use 0.3 as the FP rate warning threshold."""
        source = CARDS_PATH.read_text()
        assert "0.3" in source, "FP rate threshold 0.3 missing from cards.py"

    def test_fp_rate_cold_start_none(self):
        """alerts.py must check total > 0 to avoid division by zero on cold start."""
        source = ALERTS_PATH.read_text()
        assert "fp_total > 0" in source or "total > 0" in source, "Cold start guard (total > 0) missing from alerts.py"


# ---------------------------------------------------------------------------
# Import helper — load cards.py via spec_from_file_location
# ---------------------------------------------------------------------------


def _import_cards():
    """Import cards module from source path."""
    service_dir = str(REPO_ROOT / "services" / "slack-bot")
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
    """Import cards module fresh."""
    return _import_cards()


# ---------------------------------------------------------------------------
# Shared card builder kwargs
# ---------------------------------------------------------------------------

_BASE_CARD_KWARGS = {
    "task_id": "task-001",
    "patient_hash": "p-abc123",
    "alert_type": "high_glucose",
    "severity": "URGENT",
    "timestamp": "2026-03-18T12:00:00Z",
    "ai_summary": "Elevated glucose detected.",
    "hasura_url": "http://hasura:8080/v1/graphql",
}


def _find_fp_warning_block(blocks: list[dict]) -> dict | None:
    """Find the FP rate warning context block in the card, if present."""
    for block in blocks:
        if block.get("type") == "context":
            elements = block.get("elements", [])
            for el in elements:
                if "false-positive" in el.get("text", "").lower():
                    return block
    return None


# ---------------------------------------------------------------------------
# Unit tests — exercise alert_card with various fp_rate values
# ---------------------------------------------------------------------------


class TestAlertCardFPBadge:
    """Unit tests for FP rate warning badge in alert_card."""

    def test_alert_card_no_fp_badge_when_none(self, cards_module):
        """No FP warning block when fp_rate is None."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=None)
        warning = _find_fp_warning_block(blocks)
        assert warning is None, "FP warning should not appear when fp_rate is None"

    def test_alert_card_no_fp_badge_when_low(self, cards_module):
        """No FP warning block when fp_rate is below threshold (0.1)."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=0.1)
        warning = _find_fp_warning_block(blocks)
        assert warning is None, "FP warning should not appear when fp_rate is 0.1"

    def test_alert_card_fp_badge_when_high(self, cards_module):
        """FP warning block present when fp_rate is high (0.45)."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=0.45)
        warning = _find_fp_warning_block(blocks)
        assert warning is not None, "FP warning should appear when fp_rate is 0.45"
        text = warning["elements"][0]["text"]
        assert "⚠️" in text, "Warning emoji missing"
        assert "45%" in text, "FP rate percentage missing"

    def test_alert_card_fp_badge_at_threshold(self, cards_module):
        """FP warning block present at exact threshold (0.3)."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=0.3)
        warning = _find_fp_warning_block(blocks)
        assert warning is not None, "FP warning should appear at exact threshold 0.3"
        text = warning["elements"][0]["text"]
        assert "30%" in text, "FP rate percentage missing at threshold"

    def test_alert_card_fp_badge_contains_alert_type(self, cards_module):
        """FP warning block includes the alert_type for context."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=0.5)
        warning = _find_fp_warning_block(blocks)
        assert warning is not None
        text = warning["elements"][0]["text"]
        assert "high_glucose" in text, "Alert type missing from FP warning"

    def test_alert_card_block_count_without_fp(self, cards_module):
        """Card has 7 blocks without FP warning (header + fields + div + ai + signals + div + actions)."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=None)
        assert len(blocks) == 7, f"Expected 7 blocks without FP warning, got {len(blocks)}"

    def test_alert_card_block_count_with_fp(self, cards_module):
        """Card has 8 blocks with FP warning (extra context block before actions)."""
        blocks = cards_module.alert_card(**_BASE_CARD_KWARGS, fp_rate=0.5)
        assert len(blocks) == 8, f"Expected 8 blocks with FP warning, got {len(blocks)}"
        # FP warning is second-to-last, actions is last
        assert blocks[-2]["type"] == "context", "FP warning block should be before actions"
        assert blocks[-1]["type"] == "actions", "Actions should be last block"
