"""Source-inspection tests for PRIORITY_UPGRADE in rules.py.

Verifies the escalation priority upgrade map exists and contains
the correct low->medium->high->critical mappings. Uses importlib.util
to load rules.py directly (no heavy service dependencies).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "services" / "control-plane" / "src" / "rules.py"


def _source() -> str:
    return SOURCE.read_text()


def test_source_file_exists():
    assert SOURCE.exists(), f"Expected source file at {SOURCE}"


def test_priority_upgrade_variable_exists():
    src = _source()
    assert "PRIORITY_UPGRADE" in src


def test_priority_upgrade_keys_in_source():
    src = _source()
    # Verify the dict contains the expected keys via regex
    assert re.search(r'"low"\s*:', src), "PRIORITY_UPGRADE must contain 'low' key"
    assert re.search(r'"medium"\s*:', src), "PRIORITY_UPGRADE must contain 'medium' key"
    assert re.search(r'"high"\s*:', src), "PRIORITY_UPGRADE must contain 'high' key"


def test_priority_upgrade_dict_values():
    """Verify dict maps low->medium, medium->high, high->critical via regex."""
    src = _source()
    assert re.search(r'"low"\s*:\s*"medium"', src), "low must map to medium"
    assert re.search(r'"medium"\s*:\s*"high"', src), "medium must map to high"
    assert re.search(r'"high"\s*:\s*"critical"', src), "high must map to critical"
    # critical is intentionally absent (stays critical -- posts UNCLAIMED CRITICAL instead)
    assert not re.search(r'"critical"\s*:\s*"', src), "critical must NOT have an upgrade target in PRIORITY_UPGRADE"
