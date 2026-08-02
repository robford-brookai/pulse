"""SLACK-CONN-05: Slash commands — /ocean status, patient, sim, help."""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

SERVICES_ROOT = Path(__file__).resolve().parents[2] / "services" / "slack-bot"
SLASH_COMMANDS_PATH = SERVICES_ROOT / "src" / "slash_commands.py"
BOLT_APP_PATH = SERVICES_ROOT / "src" / "bolt_app.py"


def _read_source(path: Path) -> str:
    return path.read_text()


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


class TestSlashCommandsSourceInspection:
    """Verify slash_commands.py structure via source inspection."""

    def test_has_handle_ocean_command(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "async def handle_ocean_command" in source

    def test_has_build_status_response(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "async def build_status_response" in source

    def test_has_build_patient_response(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "async def build_patient_response" in source

    def test_has_trigger_sim_response(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "async def trigger_sim_response" in source

    def test_has_build_help_response(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "def build_help_response" in source

    def test_has_set_slash_deps(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "def set_slash_deps(" in source

    def test_uses_graphql_for_hasura(self):
        source = _read_source(SLASH_COMMANDS_PATH)
        assert "graphql" in source.lower()


class TestBoltAppSlashRegistration:
    """Verify bolt_app.py registers /ocean command."""

    def test_imports_handle_ocean_command(self):
        source = _read_source(BOLT_APP_PATH)
        assert "handle_ocean_command" in source

    def test_registers_ocean_command(self):
        source = _read_source(BOLT_APP_PATH)
        assert re.search(r'command.*["\']/ocean["\']', source) or \
               re.search(r'["\']/ocean["\']', source)


# ---------------------------------------------------------------------------
# Unit tests (import-based)
# ---------------------------------------------------------------------------


@pytest.fixture
def _clear_slash_modules():
    """Ensure clean imports of slash_commands."""
    import sys
    keys_to_remove = [k for k in sys.modules if "slash_commands" in k]
    for k in keys_to_remove:
        del sys.modules[k]
    yield
    keys_to_remove = [k for k in sys.modules if "slash_commands" in k]
    for k in keys_to_remove:
        del sys.modules[k]


def _import_slash_commands():
    """Import slash_commands module from source path."""
    import importlib.util
    import sys

    # Add services/slack-bot to path temporarily
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


class TestHandleOceanCommand:
    """Unit tests for the /ocean command handler."""

    @pytest.mark.asyncio
    async def test_ack_called_first(self, _clear_slash_modules):
        """ack() must be called before respond()."""
        mod = _import_slash_commands()

        call_order = []
        ack = AsyncMock(
            side_effect=lambda: call_order.append("ack"),
        )
        respond = AsyncMock(
            side_effect=lambda **kw: call_order.append("respond"),
        )
        body = {"text": "help", "user_id": "U123"}

        await mod.handle_ocean_command(
            ack=ack, body=body, respond=respond,
        )

        assert call_order[0] == "ack"

    @pytest.mark.asyncio
    async def test_status_subcommand(self, _clear_slash_modules):
        """'status' subcommand calls build_status_response."""
        mod = _import_slash_commands()
        ack = AsyncMock()
        respond = AsyncMock()
        body = {"text": "status", "user_id": "U123"}
        block = [{"type": "section", "text": {"type": "mrkdwn", "text": "t"}}]

        with patch.object(
            mod, "build_status_response", new_callable=AsyncMock,
        ) as mock_status:
            mock_status.return_value = block
            await mod.handle_ocean_command(
                ack=ack, body=body, respond=respond,
            )
            mock_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_patient_subcommand_passes_id(self, _clear_slash_modules):
        """'patient P123' passes P123 to build_patient_response."""
        mod = _import_slash_commands()
        ack = AsyncMock()
        respond = AsyncMock()
        body = {"text": "patient P123", "user_id": "U123"}
        block = [{"type": "section", "text": {"type": "mrkdwn", "text": "t"}}]

        with patch.object(
            mod, "build_patient_response", new_callable=AsyncMock,
        ) as mock_patient:
            mock_patient.return_value = block
            await mod.handle_ocean_command(
                ack=ack, body=body, respond=respond,
            )
            mock_patient.assert_awaited_once_with("P123")

    @pytest.mark.asyncio
    async def test_sim_subcommand_passes_scenario(self, _clear_slash_modules):
        """'sim pilot_demo' passes pilot_demo to trigger_sim_response."""
        mod = _import_slash_commands()
        ack = AsyncMock()
        respond = AsyncMock()
        body = {"text": "sim pilot_demo", "user_id": "U123"}
        block = [{"type": "section", "text": {"type": "mrkdwn", "text": "t"}}]

        with patch.object(
            mod, "trigger_sim_response", new_callable=AsyncMock,
        ) as mock_sim:
            mock_sim.return_value = block
            await mod.handle_ocean_command(
                ack=ack, body=body, respond=respond,
            )
            mock_sim.assert_awaited_once_with("pilot_demo")

    @pytest.mark.asyncio
    async def test_empty_text_returns_help(self, _clear_slash_modules):
        """Empty text defaults to help."""
        mod = _import_slash_commands()
        ack = AsyncMock()
        respond = AsyncMock()
        body = {"text": "", "user_id": "U123"}
        block = [{"type": "section", "text": {"type": "mrkdwn", "text": "h"}}]

        with patch.object(mod, "build_help_response") as mock_help:
            mock_help.return_value = block
            await mod.handle_ocean_command(
                ack=ack, body=body, respond=respond,
            )
            mock_help.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_subcommand_returns_help(self, _clear_slash_modules):
        """Unknown subcommand returns help response."""
        mod = _import_slash_commands()
        ack = AsyncMock()
        respond = AsyncMock()
        body = {"text": "foobar", "user_id": "U123"}
        block = [{"type": "section", "text": {"type": "mrkdwn", "text": "h"}}]

        with patch.object(mod, "build_help_response") as mock_help:
            mock_help.return_value = block
            await mod.handle_ocean_command(
                ack=ack, body=body, respond=respond,
            )
            mock_help.assert_called_once()


class TestBuildHelpResponse:
    """Unit tests for build_help_response."""

    def test_mentions_all_subcommands(self, _clear_slash_modules):
        """Help response mentions all 4 subcommands."""
        mod = _import_slash_commands()
        blocks = mod.build_help_response()
        text = str(blocks)
        for cmd in ["status", "patient", "sim", "help"]:
            assert cmd in text, f"Help should mention '{cmd}' subcommand"
