"""ESC-05: Escalation policies defined as rules-as-code in escalation.py.

Source-inspection test: verifies escalation.py contains ESCALATION_THRESHOLDS,
PRIORITY_UPGRADE import from rules, and env-var reads.
"""
from __future__ import annotations

import pathlib


ESCALATION_PY = pathlib.Path("services/control-plane/src/escalation.py")
RULES_PY = pathlib.Path("services/control-plane/src/rules.py")


def test_escalation_module_contains_thresholds():
    """escalation.py defines ESCALATION_THRESHOLDS dict."""
    src = ESCALATION_PY.read_text()
    assert "ESCALATION_THRESHOLDS" in src


def test_escalation_module_reads_env_vars():
    """escalation.py reads timeout thresholds from environment variables."""
    src = ESCALATION_PY.read_text()
    assert 'os.environ.get("ESCALATION_TIMEOUT_CRITICAL"' in src
    assert 'os.environ.get("ESCALATION_TIMEOUT_HIGH"' in src
    assert 'os.environ.get("ESCALATION_TIMEOUT_MEDIUM"' in src
    assert 'os.environ.get("ESCALATION_TIMEOUT_LOW"' in src


def test_escalation_module_imports_priority_upgrade():
    """escalation.py imports PRIORITY_UPGRADE from rules."""
    src = ESCALATION_PY.read_text()
    assert "from src.rules import PRIORITY_UPGRADE" in src


def test_rules_module_defines_priority_upgrade():
    """rules.py defines PRIORITY_UPGRADE mapping."""
    src = RULES_PY.read_text()
    assert "PRIORITY_UPGRADE" in src
    # Verify the mapping values
    assert '"low": "medium"' in src or "'low': 'medium'" in src
    assert '"medium": "high"' in src or "'medium': 'high'" in src
    assert '"high": "critical"' in src or "'high': 'critical'" in src


def test_escalation_module_has_enabled_flag():
    """escalation.py reads ESCALATION_ENABLED from environment."""
    src = ESCALATION_PY.read_text()
    assert "ESCALATION_ENABLED" in src


def test_escalation_module_exports_key_functions():
    """escalation.py defines all required public functions."""
    src = ESCALATION_PY.read_text()
    for fn in [
        "def find_escalation_candidates(",
        "def check_and_escalate(",
        "def run_escalation_poller(",
        "def rehydrate_and_catch_up(",
        "def insert_escalation_state(",
        "def remove_escalation_state(",
    ]:
        assert fn in src, f"Missing function: {fn}"
