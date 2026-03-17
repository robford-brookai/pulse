"""DEMO-05: AI key detection in banner.

Verifies banner output warns about missing ANTHROPIC_API_KEY and shows
ENABLED when the key is set.
"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def demo_module():
    import importlib

    if "demo" in sys.modules:
        del sys.modules["demo"]
    return importlib.import_module("demo")


def _capture_banner(demo_module, warehouse=False, env_override=None):
    scenario_meta = {"scenario": "pilot_demo", "patients": 50, "expected_events": 100}
    buf = io.StringIO()
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    with patch.dict(os.environ, env, clear=True):
        with redirect_stdout(buf):
            demo_module.print_banner(scenario_meta, warehouse=warehouse)
    return buf.getvalue()


def test_banner_ai_unavailable_without_key(demo_module):
    """Without ANTHROPIC_API_KEY, banner warns about unavailability."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    output = _capture_banner(demo_module, env_override=env)
    assert "UNAVAILABLE" in output or "unavailable" in output.lower()


def test_banner_ai_enabled_with_key(demo_module):
    """With ANTHROPIC_API_KEY set, banner shows ENABLED."""
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
    output = _capture_banner(demo_module, env_override=env)
    assert "ENABLED" in output


def test_banner_ai_hint_when_missing(demo_module):
    """Without key, banner includes setup hint with ANTHROPIC_API_KEY."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    output = _capture_banner(demo_module, env_override=env)
    assert "ANTHROPIC_API_KEY" in output
