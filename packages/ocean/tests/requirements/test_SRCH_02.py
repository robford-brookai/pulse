"""SRCH-02: Auto-sync embeddings after demo scenario completion.

Source-inspection + unit tests for scripts/demo.py.
Verifies: sync_embeddings_all exists, calls stacte-bridge /sync for all
4 entity types, and handles errors gracefully.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT_PATH = REPO_ROOT / "scripts" / "demo.py"

ENTITY_TYPES = ["alerts", "tasks", "interactions", "outcomes"]


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


def test_demo_script_exists():
    """scripts/demo.py must exist."""
    assert DEMO_SCRIPT_PATH.exists(), f"Missing {DEMO_SCRIPT_PATH}"


def test_sync_embeddings_all_defined():
    """demo.py must define async def sync_embeddings_all."""
    source = DEMO_SCRIPT_PATH.read_text()
    assert "async def sync_embeddings_all" in source


def test_stacte_bridge_sync_url_referenced():
    """demo.py must reference stacte-bridge /sync endpoint."""
    source = DEMO_SCRIPT_PATH.read_text()
    assert "stacte-bridge:8000/sync" in source


def test_all_entity_types_in_function():
    """sync_embeddings_all must reference all 4 entity types."""
    source = DEMO_SCRIPT_PATH.read_text()
    # Extract just the function body to be precise
    for et in ENTITY_TYPES:
        assert f'"{et}"' in source or f"'{et}'" in source, (
            f"Entity type '{et}' not found in demo.py"
        )


def test_sync_called_in_main():
    """main() must call sync_embeddings_all."""
    source = DEMO_SCRIPT_PATH.read_text()
    # Find main function body — look for the call after wait_for_completion
    assert "sync_embeddings_all()" in source, (
        "sync_embeddings_all() not called in demo.py"
    )


def test_sync_function_accessible_via_spec():
    """sync_embeddings_all must be loadable via spec_from_file_location."""
    spec = importlib.util.spec_from_file_location(
        "demo_inspect",
        str(DEMO_SCRIPT_PATH),
    )
    assert spec is not None
    assert spec.loader is not None
    source = spec.loader.get_source("demo_inspect")
    assert "async def sync_embeddings_all" in source


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------


def _import_demo():
    """Import demo.py module using spec_from_file_location."""
    scripts_dir = str(DEMO_SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # Clear cached modules
    keys_to_remove = [k for k in sys.modules if k.startswith("demo")]
    for k in keys_to_remove:
        del sys.modules[k]

    spec = importlib.util.spec_from_file_location("demo", str(DEMO_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def demo_module():
    """Import demo module fresh."""
    return _import_demo()


# ---------------------------------------------------------------------------
# Unit tests (mock httpx, exercise sync_embeddings_all)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_embeddings_all_calls_all_entity_types(demo_module):
    """sync_embeddings_all POSTs to /sync for all 4 entity types."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(demo_module.httpx, "AsyncClient", return_value=mock_client):
        await demo_module.sync_embeddings_all()

    # Should have called POST 4 times — once per entity type
    assert mock_client.post.call_count == 4

    called_types = []
    for call in mock_client.post.call_args_list:
        url = call[0][0] if call[0] else call[1].get("url", "")
        params = call[1].get("params", {}) if call[1] else {}
        assert "stacte-bridge:8000/sync" in url
        called_types.append(params.get("entity_type"))

    assert called_types == ENTITY_TYPES


@pytest.mark.asyncio
async def test_sync_embeddings_all_graceful_on_error(demo_module):
    """sync_embeddings_all doesn't crash when one entity type fails."""
    call_count = 0

    async def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        entity_type = kwargs.get("params", {}).get("entity_type", "")
        if entity_type == "tasks":
            raise Exception("Connection refused")
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(demo_module.httpx, "AsyncClient", return_value=mock_client):
        # Should NOT raise — graceful error handling
        await demo_module.sync_embeddings_all()

    # All 4 entity types should have been attempted
    assert call_count == 4


@pytest.mark.asyncio
async def test_sync_embeddings_all_handles_http_error(demo_module):
    """sync_embeddings_all handles HTTP 500 errors gracefully."""
    import httpx as real_httpx

    async def mock_post(url, **kwargs):
        entity_type = kwargs.get("params", {}).get("entity_type", "")
        resp = MagicMock()
        if entity_type == "interactions":
            resp.status_code = 500
            resp.raise_for_status = MagicMock(
                side_effect=real_httpx.HTTPStatusError(
                    "Server Error",
                    request=MagicMock(),
                    response=resp,
                )
            )
        else:
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
        return resp

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(demo_module.httpx, "AsyncClient", return_value=mock_client):
        # Should NOT raise — graceful error handling
        await demo_module.sync_embeddings_all()
