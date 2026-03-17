"""DEMO-01: Demo orchestration script exists with core functions.

Source-inspection + unit tests for scripts/demo.py.
Verifies health polling, scenario triggering, completion detection, and banner output.
"""
from __future__ import annotations

import asyncio
import inspect
import io
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo.py"


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


def test_demo_script_exists():
    """scripts/demo.py must exist."""
    assert DEMO_SCRIPT.exists(), f"Missing {DEMO_SCRIPT}"


def test_demo_script_has_wait_for_health():
    """scripts/demo.py must define async def wait_for_health."""
    source = DEMO_SCRIPT.read_text()
    assert "async def wait_for_health" in source


def test_demo_script_has_trigger_scenario():
    """scripts/demo.py must define async def trigger_scenario."""
    source = DEMO_SCRIPT.read_text()
    assert "async def trigger_scenario" in source


def test_demo_script_has_wait_for_completion():
    """scripts/demo.py must define async def wait_for_completion."""
    source = DEMO_SCRIPT.read_text()
    assert "async def wait_for_completion" in source


def test_demo_script_has_print_banner():
    """scripts/demo.py must define def print_banner."""
    source = DEMO_SCRIPT.read_text()
    assert "def print_banner" in source


def test_demo_script_references_simulate_endpoint():
    """scripts/demo.py must POST to sim-driver /simulate."""
    source = DEMO_SCRIPT.read_text()
    assert "localhost:8060/simulate" in source


def test_demo_script_references_active_scenarios():
    """scripts/demo.py must check active_scenarios for completion."""
    source = DEMO_SCRIPT.read_text()
    assert "active_scenarios" in source


# ---------------------------------------------------------------------------
# Unit tests (import and exercise functions)
# ---------------------------------------------------------------------------

# Add scripts/ to path so we can import demo module
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def demo_module():
    """Import demo module fresh."""
    import importlib

    if "demo" in sys.modules:
        del sys.modules["demo"]
    mod = importlib.import_module("demo")
    return mod


@pytest.mark.asyncio
async def test_wait_for_health_success(demo_module):
    """wait_for_health returns when all services respond 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    services = {"svc1": "http://localhost:8001/health", "svc2": "http://localhost:8002/health"}

    with patch("demo.httpx.AsyncClient", return_value=mock_client):
        await demo_module.wait_for_health(services, timeout=5)

    # If we get here without TimeoutError, test passes


@pytest.mark.asyncio
async def test_wait_for_health_timeout(demo_module):
    """wait_for_health raises TimeoutError when services are unhealthy."""
    import httpx as real_httpx

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=real_httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    services = {"svc1": "http://localhost:9999/health"}

    with patch("demo.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(TimeoutError, match="svc1"):
            await demo_module.wait_for_health(services, timeout=1)


@pytest.mark.asyncio
async def test_trigger_scenario_posts_correctly(demo_module):
    """trigger_scenario POSTs to /simulate with the scenario name."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": "started",
        "scenario": "pilot_demo",
        "patients": 50,
        "expected_events": 100,
        "estimated_duration_seconds": 5.0,
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("demo.httpx.AsyncClient", return_value=mock_client):
        result = await demo_module.trigger_scenario("pilot_demo")

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "localhost:8060/simulate" in call_args[0][0]
    assert call_args[1]["json"] == {"scenario": "pilot_demo"}
    assert result["patients"] == 50
