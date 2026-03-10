"""SLACK-CONN-03: MCP server with 12 tools, API key middleware, mounted at /mcp."""
from __future__ import annotations

import ast
import importlib
import os
import re
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

SERVICES_ROOT = Path(__file__).resolve().parents[2] / "services" / "slack-bot"
MCP_SERVER_PATH = SERVICES_ROOT / "src" / "mcp_server.py"
MAIN_PATH = SERVICES_ROOT / "src" / "main.py"


# ---------------------------------------------------------------------------
# Source-inspection helpers
# ---------------------------------------------------------------------------

def _read_source(path: Path) -> str:
    return path.read_text()


def _count_decorator(source: str, decorator: str) -> int:
    """Count occurrences of a decorator in source code."""
    return len(re.findall(rf"@{re.escape(decorator)}", source))


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


class TestMCPServerSourceInspection:
    """Verify mcp_server.py structure via source inspection."""

    def test_has_12_mcp_tool_decorators(self):
        source = _read_source(MCP_SERVER_PATH)
        count = _count_decorator(source, "mcp.tool()")
        assert count == 12, f"Expected 12 @mcp.tool() decorators, found {count}"

    def test_tool_names_follow_domain_action_convention(self):
        source = _read_source(MCP_SERVER_PATH)
        tree = ast.parse(source)
        tool_funcs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        if dec.func.attr == "tool":
                            tool_funcs.append(node.name)
        expected_prefixes = {"slack_", "ocean_", "sim_"}
        for name in tool_funcs:
            prefix = name.split("_")[0] + "_"
            assert prefix in expected_prefixes, (
                f"Tool '{name}' doesn't follow domain_action naming (expected prefix in {expected_prefixes})"
            )

    def test_expected_tools_present(self):
        source = _read_source(MCP_SERVER_PATH)
        expected = [
            "slack_send_message", "slack_post_card", "slack_read_channel",
            "slack_react", "slack_update_message", "slack_list_channels",
            "ocean_get_task_status", "ocean_get_patient_summary",
            "ocean_list_open_tasks", "ocean_event_replay",
            "sim_trigger", "ocean_service_health",
        ]
        for tool_name in expected:
            assert f"async def {tool_name}" in source, f"Missing tool: {tool_name}"

    def test_set_mcp_deps_function_exists(self):
        source = _read_source(MCP_SERVER_PATH)
        assert "def set_mcp_deps(" in source

    def test_create_mcp_app_function_exists(self):
        source = _read_source(MCP_SERVER_PATH)
        assert "def create_mcp_app(" in source


class TestMainSourceInspection:
    """Verify main.py has MCP mounting and middleware."""

    def test_imports_mcp_server(self):
        source = _read_source(MAIN_PATH)
        assert "mcp_server" in source, "main.py should import from mcp_server"

    def test_has_mcp_api_key_middleware(self):
        source = _read_source(MAIN_PATH)
        assert "MCPApiKeyMiddleware" in source, "main.py should define MCPApiKeyMiddleware"

    def test_mounts_mcp_app(self):
        source = _read_source(MAIN_PATH)
        assert re.search(r'mount.*["\']\/mcp["\']', source), (
            "main.py should mount MCP app at /mcp"
        )

    def test_middleware_checks_x_api_key(self):
        source = _read_source(MAIN_PATH)
        assert "X-Api-Key" in source, "Middleware should check X-Api-Key header"


# ---------------------------------------------------------------------------
# Unit tests for MCPApiKeyMiddleware
# ---------------------------------------------------------------------------


class TestMCPApiKeyMiddleware:
    """Unit tests for API key enforcement on /mcp paths."""

    @pytest.fixture(autouse=True)
    def _load_middleware(self):
        """Import MCPApiKeyMiddleware from main.py using isolated import."""
        # Clear cached src.* modules to avoid cross-service collisions
        to_remove = [k for k in sys.modules if k.startswith("src.") or k == "src"]
        for k in to_remove:
            del sys.modules[k]

        spec = importlib.util.spec_from_file_location("slack_bot_main", MAIN_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Patch heavy imports that aren't needed for middleware testing
        with patch.dict(sys.modules, {
            "slack_sdk": type(sys)("slack_sdk"),
            "slack_sdk.web.async_client": type(sys)("slack_sdk.web.async_client"),
            "slack_bolt": type(sys)("slack_bolt"),
            "slack_bolt.async_app": type(sys)("slack_bolt.async_app"),
            "slack_bolt.adapter.fastapi.async_handler": type(sys)("slack_bolt.adapter.fastapi.async_handler"),
            "confluent_kafka": type(sys)("confluent_kafka"),
        }):
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass
        self.middleware_cls = getattr(mod, "MCPApiKeyMiddleware", None)
        assert self.middleware_cls is not None, "MCPApiKeyMiddleware not found in main.py"

    @pytest.mark.asyncio
    async def test_returns_401_when_api_key_missing(self):
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        async def mcp_endpoint(request):
            return PlainTextResponse("ok")

        test_app = Starlette(routes=[Route("/mcp/sse", mcp_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/mcp/sse")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_passes_through_with_correct_key(self):
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        async def mcp_endpoint(request):
            return PlainTextResponse("ok")

        test_app = Starlette(routes=[Route("/mcp/sse", mcp_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/mcp/sse", headers={"X-Api-Key": "test-secret-key"})
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_passes_through_for_non_mcp_paths(self):
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        async def health_endpoint(request):
            return PlainTextResponse("healthy")

        test_app = Starlette(routes=[Route("/health", health_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.status_code == 200
