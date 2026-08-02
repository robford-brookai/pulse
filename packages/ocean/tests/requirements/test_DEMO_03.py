"""DEMO-03: Banner includes GraphQL query and Hasura URL.

Verifies print_banner output contains patient_timeline query, sim-pt-demo-001,
and the Hasura console URL.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

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
    """Call print_banner and capture stdout."""
    scenario_meta = {
        "scenario": "pilot_demo",
        "patients": 50,
        "expected_events": 100,
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_module.print_banner(scenario_meta, warehouse=warehouse)
    return buf.getvalue()


def test_banner_contains_patient_timeline(demo_module):
    """Banner must include the patient_timeline GraphQL query."""
    output = _capture_banner(demo_module)
    assert "patient_timeline" in output


def test_banner_contains_demo_patient_id(demo_module):
    """Banner must include sim-pt-demo-001 as example patient."""
    output = _capture_banner(demo_module)
    assert "sim-pt-demo-001" in output


def test_banner_contains_hasura_url(demo_module):
    """Banner must include Hasura console URL."""
    output = _capture_banner(demo_module)
    assert "http://localhost:8090" in output
