"""Source-inspection tests: sim-profile Dockerfiles suppress access logs."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_dockerfile_cmd(service: str) -> str:
    """Read the CMD line from a service Dockerfile."""
    dockerfile = REPO_ROOT / "services" / service / "Dockerfile"
    for line in dockerfile.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("CMD"):
            return stripped
    raise AssertionError(f"No CMD line found in {dockerfile}")


def test_sim_driver_no_access_log():
    cmd = _read_dockerfile_cmd("sim-driver")
    assert "--no-access-log" in cmd, f"sim-driver CMD missing --no-access-log: {cmd}"


def test_agent_worker_no_access_log():
    cmd = _read_dockerfile_cmd("agent-worker")
    assert "--no-access-log" in cmd, f"agent-worker CMD missing --no-access-log: {cmd}"


def test_call_simulator_no_access_log():
    cmd = _read_dockerfile_cmd("call-simulator")
    assert "--no-access-log" in cmd, f"call-simulator CMD missing --no-access-log: {cmd}"
