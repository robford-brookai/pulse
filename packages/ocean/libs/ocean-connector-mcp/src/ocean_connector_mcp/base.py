"""ConnectorMCP -- base class for Ocean departmental connector MCP servers.

Provides tool registration, ASGI app creation, API key middleware,
and a default health tool. Each connector inherits from this class
and registers domain-specific tools via the @connector.tool decorator.
"""

from __future__ import annotations

import os
from typing import Any, cast

import structlog
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

log = structlog.get_logger()


class ConnectorMCP:
    """Base class for Ocean connector MCP servers.

    Usage::

        connector = ConnectorMCP("My Connector", "Description")

        @connector.tool
        async def my_tool(arg: str) -> dict:
            return {"result": arg}

        app = connector.create_asgi_app(path="/")
    """

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self.mcp = FastMCP(name)
        self._register_health_tool()

    def _register_health_tool(self) -> None:
        """Register a default health tool."""
        connector_name = self.name

        @self.mcp.tool()
        async def health() -> dict:
            """Return connector health status."""
            return {"status": "ok", "connector": connector_name}

    @property
    def tool(self) -> Any:
        """Decorator to register an MCP tool.

        Delegates to the underlying FastMCP instance::

            @connector.tool
            async def my_tool(x: int) -> dict:
                return {"value": x}
        """
        return self.mcp.tool

    def create_asgi_app(self, path: str = "/") -> Starlette:
        """Create an ASGI app for mounting in a FastAPI service.

        Args:
            path: The SSE path within the mounted app.

        Returns:
            A Starlette ASGI application.
        """
        return self.mcp.http_app(path=path)

    async def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        tools = await self.mcp.list_tools()
        return [t.name for t in tools]

    @staticmethod
    def api_key_middleware(
        env_var: str = "MCP_API_KEY",
        path_prefix: str = "/mcp",
    ) -> type:
        """Return a Starlette middleware class for API key auth.

        The middleware checks the ``X-Api-Key`` header against the
        value of the specified environment variable for any request
        whose path starts with ``path_prefix``.

        Args:
            env_var: Environment variable holding the expected key.
            path_prefix: URL prefix to protect.

        Returns:
            A BaseHTTPMiddleware subclass.
        """
        _env_var = env_var
        _path_prefix = path_prefix

        class _ApiKeyMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Any, call_next: Any) -> Response:
                if request.url.path.startswith(_path_prefix):
                    api_key = request.headers.get("X-Api-Key", "")
                    expected = os.environ.get(_env_var, "")
                    if not expected or api_key != expected:
                        return JSONResponse(
                            {"error": "unauthorized"},
                            status_code=401,
                        )
                return cast(Response, await call_next(request))

        return _ApiKeyMiddleware
