"""SLACK-CONN-03: MCP server with 12 tools, API key middleware, mounted at /mcp."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

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
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "tool":
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
            "slack_send_message",
            "slack_post_card",
            "slack_read_channel",
            "slack_react",
            "slack_update_message",
            "slack_list_channels",
            "ocean_get_task_status",
            "ocean_get_patient_summary",
            "ocean_list_open_tasks",
            "ocean_event_replay",
            "sim_trigger",
            "ocean_service_health",
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
        assert re.search(r'mount.*["\']\/mcp["\']', source), "main.py should mount MCP app at /mcp"

    def test_middleware_checks_x_api_key(self):
        source = _read_source(MAIN_PATH)
        assert "X-Api-Key" in source, "Middleware should check X-Api-Key header"

    def test_middleware_uses_mcp_api_key_env(self):
        source = _read_source(MAIN_PATH)
        assert "MCP_API_KEY" in source, "Middleware should read MCP_API_KEY from env"


# ---------------------------------------------------------------------------
# Unit tests for MCPApiKeyMiddleware behavior
# ---------------------------------------------------------------------------
# We extract the middleware logic from main.py source via AST and reconstruct
# it here to test in isolation, avoiding heavy service dependency imports.


def _build_middleware_from_source() -> type:
    """Parse MCPApiKeyMiddleware from main.py source and return the class."""
    source = _read_source(MAIN_PATH)
    tree = ast.parse(source)

    # Find the MCPApiKeyMiddleware class definition
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MCPApiKeyMiddleware":
            # Reconstruct the class in a clean namespace
            class_source = ast.get_source_segment(source, node)
            namespace = {
                "BaseHTTPMiddleware": BaseHTTPMiddleware,
                "JSONResponse": JSONResponse,
                "os": os,
            }
            exec(class_source, namespace)  # noqa: S102
            return namespace["MCPApiKeyMiddleware"]

    raise RuntimeError("MCPApiKeyMiddleware not found in main.py")


class TestMCPApiKeyMiddleware:
    """Unit tests for API key enforcement on /mcp paths."""

    @pytest.fixture(autouse=True)
    def _load_middleware(self):
        self.middleware_cls = _build_middleware_from_source()

    def test_returns_401_when_api_key_missing(self):
        async def mcp_endpoint(request):
            return PlainTextResponse("ok")

        test_app = Starlette(routes=[Route("/mcp/sse", mcp_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/mcp/sse")
            assert resp.status_code == 401

    def test_returns_401_when_api_key_wrong(self):
        async def mcp_endpoint(request):
            return PlainTextResponse("ok")

        test_app = Starlette(routes=[Route("/mcp/sse", mcp_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/mcp/sse", headers={"X-Api-Key": "wrong-key"})
            assert resp.status_code == 401

    def test_passes_through_with_correct_key(self):
        async def mcp_endpoint(request):
            return PlainTextResponse("ok")

        test_app = Starlette(routes=[Route("/mcp/sse", mcp_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/mcp/sse", headers={"X-Api-Key": "test-secret-key"})
            assert resp.status_code == 200

    def test_passes_through_for_non_mcp_paths(self):
        async def health_endpoint(request):
            return PlainTextResponse("healthy")

        test_app = Starlette(routes=[Route("/health", health_endpoint)])
        test_app.add_middleware(self.middleware_cls)

        with patch.dict(os.environ, {"MCP_API_KEY": "test-secret-key"}):
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.status_code == 200
