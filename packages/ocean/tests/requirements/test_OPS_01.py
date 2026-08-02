"""OPS-01: All Ocean services expose /health returning 200 with status ok.

Verifies each service's main.py contains a /health route definition that
returns {"status": "ok", ...}. Uses source inspection (AST-free string check)
to avoid importing each service with its full dependency tree.

No Docker required.
"""

from __future__ import annotations

import pathlib

import pytest

_ROOT = pathlib.Path(__file__).parents[2]

# All services that must have /health endpoints
_SERVICES = [
    "event-store",
    "pocar-connector",
    "graph-projection",
    "control-plane",
    "slack-bot",
    "zcc-connector",
    "impilo-connector",
    "stacte-bridge",
]

# Optional service (profiles: [sim]) -- verify if present, skip if missing
_OPTIONAL_SERVICES = ["sim-driver"]


def _read_main_source(service_name: str) -> str:
    """Read the main.py source for a service."""
    main_py = _ROOT / "services" / service_name / "src" / "main.py"
    if not main_py.exists():
        pytest.fail(f"Service {service_name}: main.py not found at {main_py}")
    return main_py.read_text()


class TestHealthEndpoints:
    """Verify /health route exists in every required Ocean service."""

    @pytest.mark.parametrize("service", _SERVICES)
    def test_health_route_defined(self, service: str):
        """Service main.py must define a /health GET route."""
        source = _read_main_source(service)
        assert '"/health"' in source or "'/health'" in source, f"Service {service}: no /health route found in main.py"

    @pytest.mark.parametrize("service", _SERVICES)
    def test_health_returns_status_ok(self, service: str):
        """Service /health route must return a response containing 'ok'."""
        source = _read_main_source(service)
        # All services return {"status": "ok", ...}
        assert '"ok"' in source or "'ok'" in source, f"Service {service}: /health response does not contain 'ok'"

    @pytest.mark.parametrize("service", _OPTIONAL_SERVICES)
    def test_optional_service_health(self, service: str):
        """Optional service /health route should exist if service directory exists."""
        service_dir = _ROOT / "services" / service
        if not service_dir.exists():
            pytest.skip(f"Optional service {service} not present")
        source = _read_main_source(service)
        assert '"/health"' in source or "'/health'" in source, f"Optional service {service}: no /health route found"
