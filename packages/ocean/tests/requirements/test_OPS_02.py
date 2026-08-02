"""OPS-02: Docker Compose starts complete stack with single command.

Verifies infra/docker-compose.yml defines all expected services with
healthcheck definitions. No Docker required -- parses YAML only.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

_ROOT = pathlib.Path(__file__).parents[2]
_COMPOSE_PATH = _ROOT / "infra" / "docker-compose.yml"

# Infrastructure services (no healthcheck requirement in this test -- they have their own)
_INFRA_SERVICES = {"postgres", "redpanda", "redpanda-console", "redpanda-init", "migrate", "hasura", "hasura-init"}

# Application services that MUST have healthchecks
_APP_SERVICES = {
    "event-store",
    "pocar-connector",
    "graph-projection",
    "control-plane",
    "slack-bot",
    "zcc-connector",
    "impilo-connector",
    "stacte-bridge",
}

# Optional services (profiles: [sim])
_OPTIONAL_SERVICES = {"sim-driver"}

# All expected services
_ALL_EXPECTED = _INFRA_SERVICES | _APP_SERVICES | _OPTIONAL_SERVICES


@pytest.fixture(scope="module")
def compose_config() -> dict:
    """Load and return docker-compose.yml as a dict."""
    assert _COMPOSE_PATH.exists(), f"docker-compose.yml not found at {_COMPOSE_PATH}"
    return yaml.safe_load(_COMPOSE_PATH.read_text())


class TestDockerComposeStack:
    """Verify docker-compose.yml completeness and healthcheck coverage."""

    def test_compose_file_exists(self):
        """infra/docker-compose.yml must exist."""
        assert _COMPOSE_PATH.exists()

    def test_compose_valid_yaml(self, compose_config: dict):
        """docker-compose.yml must parse without errors."""
        assert "services" in compose_config, "No 'services' key in docker-compose.yml"

    def test_all_expected_services_defined(self, compose_config: dict):
        """All expected services must be defined."""
        services = set(compose_config["services"].keys())
        missing = _ALL_EXPECTED - services
        assert not missing, f"Missing services in docker-compose.yml: {missing}"

    @pytest.mark.parametrize("service", sorted(_APP_SERVICES))
    def test_app_service_has_healthcheck(self, compose_config: dict, service: str):
        """Application service must have a healthcheck definition."""
        svc = compose_config["services"].get(service)
        assert svc is not None, f"Service {service} not found in docker-compose.yml"
        assert "healthcheck" in svc, f"Service {service} missing healthcheck definition"

    def test_infrastructure_services_present(self, compose_config: dict):
        """Core infrastructure services must be defined."""
        services = set(compose_config["services"].keys())
        for svc in ("postgres", "redpanda", "migrate"):
            assert svc in services, f"Infrastructure service {svc} missing"

    def test_optional_sim_driver_has_profile(self, compose_config: dict):
        """sim-driver should use profiles: [sim] if present."""
        sim = compose_config["services"].get("sim-driver")
        if sim is None:
            pytest.skip("sim-driver not in docker-compose.yml")
        profiles = sim.get("profiles", [])
        assert "sim" in profiles, "sim-driver should have profiles: [sim]"
