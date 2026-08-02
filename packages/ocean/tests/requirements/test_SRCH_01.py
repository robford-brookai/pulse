"""SRCH-01: /ocean search slash command wired to stacte-bridge semantic search.

Source-inspection + unit tests for services/slack-bot/src/slash_commands.py.
Verifies: build_search_response exists, search subcommand routed in handler,
stacte-bridge URL referenced, and Block Kit output correct with mocked httpx.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = REPO_ROOT / "services" / "slack-bot"
SLASH_COMMANDS_PATH = SERVICES_ROOT / "src" / "slash_commands.py"


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


def test_slash_commands_exists():
    """slash_commands.py must exist."""
    assert SLASH_COMMANDS_PATH.exists(), f"Missing {SLASH_COMMANDS_PATH}"


def test_build_search_response_defined():
    """slash_commands.py must define async def build_search_response."""
    source = SLASH_COMMANDS_PATH.read_text()
    assert "async def build_search_response" in source


def test_search_subcommand_in_handler():
    """handle_ocean_command must route the 'search' subcommand."""
    source = SLASH_COMMANDS_PATH.read_text()
    assert '"search"' in source or "'search'" in source


def test_stacte_bridge_search_url_referenced():
    """slash_commands.py must call stacte-bridge /search endpoint."""
    source = SLASH_COMMANDS_PATH.read_text()
    assert "stacte-bridge:8000/search" in source


def test_help_includes_search():
    """build_help_response must mention the search subcommand."""
    source = SLASH_COMMANDS_PATH.read_text()
    assert "/ocean search" in source


def test_build_search_response_function_accessible():
    """build_search_response must be importable via spec_from_file_location."""
    spec = importlib.util.spec_from_file_location(
        "slash_commands_inspect",
        str(SLASH_COMMANDS_PATH),
    )
    assert spec is not None
    assert spec.loader is not None
    source = spec.loader.get_source("slash_commands_inspect")
    assert "async def build_search_response" in source


# ---------------------------------------------------------------------------
# Import helper (matches test_SLACK_CONN_05.py pattern)
# ---------------------------------------------------------------------------


def _import_slash_commands():
    """Import slash_commands module from source path using spec_from_file_location."""
    service_dir = str(SERVICES_ROOT)
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    # Clear cached modules to get fresh import
    keys_to_remove = [k for k in sys.modules if k.startswith("src.slash_commands")]
    for k in keys_to_remove:
        del sys.modules[k]

    spec = importlib.util.spec_from_file_location(
        "src.slash_commands", SLASH_COMMANDS_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["src.slash_commands"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def slash_module():
    """Import slash_commands module fresh."""
    return _import_slash_commands()


# ---------------------------------------------------------------------------
# Unit tests (mock httpx, exercise build_search_response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_search_response_returns_results(slash_module):
    """build_search_response returns Block Kit blocks with search results."""
    fake_results = [
        {"entity_id": "alert-001", "entity_type": "alert", "distance": 0.15},
        {"entity_id": "alert-002", "entity_type": "alert", "distance": 0.30},
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = fake_results

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.slash_commands.httpx.AsyncClient", return_value=mock_client):
        blocks = await slash_module.build_search_response("high glucose")

    # Header block + 2 result blocks
    assert len(blocks) == 3
    assert blocks[0]["type"] == "header"
    assert "high glucose" in blocks[0]["text"]["text"]

    # First result block
    text1 = blocks[1]["text"]["text"]
    assert "alert-001" in text1
    assert "Score:" in text1

    # Second result block
    text2 = blocks[2]["text"]["text"]
    assert "alert-002" in text2

    # Verify the request was made to stacte-bridge
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert "stacte-bridge:8000/search" in call_args[0][0]
    assert call_args[1]["params"]["q"] == "high glucose"


@pytest.mark.asyncio
async def test_build_search_response_empty_results(slash_module):
    """build_search_response returns 'no results' block when empty."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = []

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.slash_commands.httpx.AsyncClient", return_value=mock_client):
        blocks = await slash_module.build_search_response("nonexistent query")

    assert len(blocks) == 2  # header + no results
    assert "No results found" in blocks[1]["text"]["text"]


@pytest.mark.asyncio
async def test_build_search_response_error_handling(slash_module):
    """build_search_response returns error block when stacte-bridge is unreachable."""
    import httpx as real_httpx

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=real_httpx.ConnectError("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.slash_commands.httpx.AsyncClient", return_value=mock_client):
        blocks = await slash_module.build_search_response("test query")

    assert len(blocks) == 2  # header + error block
    assert "Error searching" in blocks[1]["text"]["text"]


@pytest.mark.asyncio
async def test_handle_ocean_command_search_routing(slash_module):
    """handle_ocean_command routes 'search' subcommand to build_search_response."""
    ack = AsyncMock()
    respond = AsyncMock()
    body = {"text": "search high glucose"}

    fake_blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "results"}}]
    with patch.object(slash_module, "build_search_response", return_value=fake_blocks) as mock_search:
        await slash_module.handle_ocean_command(ack, body, respond)

    ack.assert_called_once()
    mock_search.assert_called_once_with("high glucose")
    respond.assert_called_once_with(blocks=fake_blocks)


@pytest.mark.asyncio
async def test_handle_ocean_command_search_no_arg(slash_module):
    """handle_ocean_command shows usage when search has no argument."""
    ack = AsyncMock()
    respond = AsyncMock()
    body = {"text": "search"}

    await slash_module.handle_ocean_command(ack, body, respond)

    ack.assert_called_once()
    blocks = respond.call_args[1]["blocks"]
    assert any("Usage:" in b["text"]["text"] for b in blocks if b.get("text"))
