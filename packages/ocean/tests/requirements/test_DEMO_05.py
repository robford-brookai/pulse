"""DEMO-05: AI key detection in banner.

Verifies banner output shows ENABLED when ANTHROPIC_API_KEY is set
(via env var or .env file) and warns when missing from both.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
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


def _capture_banner(demo_module, warehouse=False):
    scenario_meta = {"scenario": "pilot_demo", "patients": 10, "expected_events": 20}
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_module.print_banner(scenario_meta, warehouse=warehouse)
    return buf.getvalue()


def test_banner_ai_enabled_with_env_key(demo_module):
    """With ANTHROPIC_API_KEY in env, banner shows ENABLED."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-key"}):
        output = _capture_banner(demo_module)
    assert "ENABLED" in output


def test_banner_ai_unavailable_without_key(demo_module):
    """Without ANTHROPIC_API_KEY in env or .env, banner warns UNAVAILABLE."""
    # Point demo.py's .env fallback to a temp file without the key
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("SOME_OTHER_VAR=foo\n")
        fake_env_path = f.name

    env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        # Patch the .env file path used by print_banner
        with patch("builtins.open", side_effect=FileNotFoundError):
            output = _capture_banner(demo_module)

    os.unlink(fake_env_path)
    assert "UNAVAILABLE" in output


def test_banner_ai_hint_when_missing(demo_module):
    """Without key, banner includes setup hint."""
    env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        with patch("builtins.open", side_effect=FileNotFoundError):
            output = _capture_banner(demo_module)
    assert "ANTHROPIC_API_KEY" in output
