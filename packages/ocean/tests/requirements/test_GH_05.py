"""GH-05: GitHub connector publishes heartbeat events on ocean.ops."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_HEARTBEAT = _ROOT / "services" / "github-connector" / "src" / "heartbeat.py"
_MAIN = _ROOT / "services" / "github-connector" / "src" / "main.py"


def test_heartbeat_module_exists():
    assert _HEARTBEAT.exists(), "heartbeat.py must exist in github-connector"


def test_heartbeat_event_type():
    src = _HEARTBEAT.read_text()
    assert '"connector.heartbeat"' in src, "Must emit connector.heartbeat event type"


def test_heartbeat_publishes_to_ocean_ops():
    src = _HEARTBEAT.read_text()
    assert '"ocean.ops"' in src, "Heartbeat must publish to ocean.ops topic"


def test_heartbeat_includes_connector_id():
    src = _HEARTBEAT.read_text()
    assert '"connector_id"' in src, "Heartbeat payload must include connector_id"


def test_main_starts_heartbeat_task():
    src = _MAIN.read_text()
    assert "publish_heartbeat" in src, "main.py must call publish_heartbeat"
    assert "github-connector" in src, "Heartbeat must identify as github-connector"


def test_health_endpoint_exists():
    src = _MAIN.read_text()
    assert '"/health"' in src, "Must expose /health endpoint"
    assert '"github-connector"' in src, "Health must return service name"
