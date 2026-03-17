"""DEMO-04: Warehouse flag behavior.

Verifies --warehouse CLI arg parsing and banner output variations.
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


def _capture_banner(demo_module, warehouse=False):
    scenario_meta = {"scenario": "pilot_demo", "patients": 50, "expected_events": 100}
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_module.print_banner(scenario_meta, warehouse=warehouse)
    return buf.getvalue()


def test_parse_args_warehouse_true(demo_module):
    """--warehouse flag sets warehouse=True."""
    args = demo_module.parse_args(["--warehouse"])
    assert args.warehouse is True


def test_parse_args_warehouse_default(demo_module):
    """No flags defaults warehouse=False."""
    args = demo_module.parse_args([])
    assert args.warehouse is False


def test_banner_warehouse_enabled(demo_module):
    """Warehouse=True banner includes dbt run instruction."""
    output = _capture_banner(demo_module, warehouse=True)
    assert "dbt run" in output.lower() or "dbt" in output


def test_banner_warehouse_disabled(demo_module):
    """Warehouse=False banner includes DISABLED message."""
    output = _capture_banner(demo_module, warehouse=False)
    assert "DISABLED" in output
