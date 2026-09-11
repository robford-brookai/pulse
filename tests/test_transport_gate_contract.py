"""`scripts/transport_gate.py` — the transport integration gate wired around the existing
LocalStack relay check (task 2.1, `critical-path-verification`).

Exercises the gate end to end with a real subprocess pytest run against small fixture test
files, not asserted from YAML: a dropped delivery and a duplicate/redrive case are each real
outcomes the gate must tell apart (a genuine failure versus a genuine pass), and a startup
failure (the environment the suite needs is unavailable, standing in for Docker/LocalStack) and
a collection failure (nothing matched the marker) each fail required mode while staying a visible
skip — or a quiet zero — in optional mode. No real Docker or LocalStack container is started;
"startup failure" is simulated the same way `test_critical_postgres_gate.py` simulates a missing
Postgres binary: a fixture that raises `pytest.fail`/`pytest.skip` itself, so the gate's
required-mode enforcement is exercised without a real environment dependency. A bounded run that
never finishes (a hung suite) must fail rather than hang the job.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "transport_gate.py"
spec = importlib.util.spec_from_file_location("transport_gate", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)

#: A delivery the transport never completes — the outbox row a relay pass could not confirm
#: publishing. The gate must report this as a real failure, in both modes: an environment gap is
#: forgivable in optional mode, a dropped delivery never is.
_DROPPED_DELIVERY_TEST = """
import pytest

@pytest.mark.integration
def test_dropped_delivery_is_not_silently_lost():
    published = False
    assert published, "committed event never reached the consumer queue"
"""

#: At-least-once redelivery is the contract (relay.py's own docstring: "an ambiguous publish
#: redelivers rather than disappears; consumers dedupe on event_id"). A duplicate arriving on
#: redrive is expected, not a defect, so the gate must pass this case cleanly.
_DUPLICATE_REDRIVE_TEST = """
import pytest

@pytest.mark.integration
def test_duplicate_redelivery_is_deduplicated_by_event_id():
    event_id = "11111111-1111-1111-1111-111111111111"
    delivered_bodies = [
        {"detail": {"event_id": event_id}},
        {"detail": {"event_id": event_id}},  # redrive redelivers the same event
    ]
    unique_ids = {b["detail"]["event_id"] for b in delivered_bodies}
    assert unique_ids == {event_id}
"""

#: Stands in for "Docker/LocalStack unavailable" without needing either: a fixture that fails
#: setup in required mode and skips visibly in optional mode, exactly the shape
#: `critical_pg_gate.ensure_pg_binaries` uses for a missing Postgres binary.
_STARTUP_FAILURE_TEST = """
import os
import pytest

@pytest.mark.integration
def test_needs_transport_environment():
    mode = os.environ["PULSE_TRANSPORT_MODE"]
    if mode == "required":
        pytest.fail("required transport mode: no LocalStack environment available")
    pytest.skip("optional local mode: no LocalStack environment available")
"""

_NOT_INTEGRATION_TEST = """
def test_unrelated():
    assert True
"""

_PASSING_INTEGRATION_TEST = """
import pytest

@pytest.mark.integration
def test_transport_roundtrip_holds():
    assert 1 + 1 == 2
"""

_HANGING_INTEGRATION_TEST = """
import time
import pytest

@pytest.mark.integration
def test_never_returns():
    time.sleep(30)
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    test_file = tmp_path / name
    test_file.write_text(body)
    return test_file


def _env_with_gate_importable() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPT_PATH.parent)
    return env


def test_help_exits_zero() -> None:
    completed = subprocess.run(  # noqa: S603 — fixed argv, our own script
        [sys.executable, str(SCRIPT_PATH), "--help"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    assert "transport" in completed.stdout


def test_dropped_delivery_fails_required_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_dropped.py", _DROPPED_DELIVERY_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is False
    assert result.failed == 1
    assert "1 failed" in result.message


def test_dropped_delivery_fails_optional_mode_too(tmp_path: Path) -> None:
    """A genuine defect is never forgiven just because the fixture mode is optional."""
    test_file = _write(tmp_path, "test_dropped.py", _DROPPED_DELIVERY_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.OPTIONAL, env=_env_with_gate_importable())
    assert result.ok is False
    assert result.failed == 1


def test_duplicate_redrive_case_passes_in_required_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_duplicate.py", _DUPLICATE_REDRIVE_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.passed == 1
    assert result.failed == 0


def test_startup_failure_fails_required_mode(tmp_path: Path) -> None:
    """GIVEN the pinned integration environment is unavailable WHEN the transport check starts
    THEN failure makes the check fail rather than passing on a quiet skip."""
    test_file = _write(tmp_path, "test_needs_env.py", _STARTUP_FAILURE_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is False
    assert result.skipped == 0  # a required-mode pytest.fail, not a skip
    assert "no LocalStack environment available" in result.message or result.failed


def test_startup_failure_is_a_visible_skip_in_optional_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_needs_env.py", _STARTUP_FAILURE_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.OPTIONAL, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.skipped == 1
    assert "no LocalStack environment available" in result.message


def test_collection_failure_fails_required_mode(tmp_path: Path) -> None:
    """GIVEN a selector collects zero transport tests WHEN required mode evaluates the result
    THEN the gate fails and identifies the missing integration coverage."""
    test_file = _write(tmp_path, "test_unrelated.py", _NOT_INTEGRATION_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is False
    assert result.collected == 0
    assert "no transport tests were collected" in result.message


def test_collection_failure_is_not_penalized_in_optional_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_unrelated.py", _NOT_INTEGRATION_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.OPTIONAL, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.collected == 0


def test_passing_transport_suite_succeeds_in_required_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_passing.py", _PASSING_INTEGRATION_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.collected == 1
    assert result.passed == 1
    assert result.skipped == 0


def test_bounded_run_fails_on_timeout_rather_than_hanging(tmp_path: Path) -> None:
    """A container that never becomes healthy — or any hung case — fails the gate, bounded."""
    test_file = _write(tmp_path, "test_hangs.py", _HANGING_INTEGRATION_TEST)
    result = gate.run_transport_suite(
        [test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable(), timeout_seconds=2.0
    )
    assert result.ok is False
    assert "timed out" in result.message


def test_run_transport_suite_reports_failure_when_evidence_is_never_produced() -> None:
    """A crashed collection (bad path) must not read as a silent pass."""
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "does-not-exist"
        result = gate.run_transport_suite(
            [missing], gate.Mode.REQUIRED, python=sys.executable, env=_env_with_gate_importable()
        )
        assert result.ok is False


def test_write_evidence_carries_required_fields_and_no_forbidden_terms(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_passing.py", _PASSING_INTEGRATION_TEST)
    result = gate.run_transport_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    out_path = tmp_path / "evidence" / "transport-gate.json"
    document = gate.write_evidence(result, [test_file], out_path)

    assert document.keys() >= gate.REQUIRED_FIELDS
    assert document["ok"] is True
    assert document["counts"]["passed"] == 1

    serialized = out_path.read_text()
    for term in gate.FORBIDDEN_TERMS:
        assert term not in serialized.lower()


def test_write_evidence_rejects_a_forbidden_term(tmp_path: Path) -> None:
    result = gate.GateResult(
        mode=gate.Mode.REQUIRED,
        ok=False,
        collected=0,
        passed=0,
        skipped=0,
        failed=0,
        errors=0,
        message="leaked a secret in the message",
    )
    with pytest.raises(RuntimeError, match="forbidden term"):
        gate.write_evidence(result, [], tmp_path / "evidence.json")


def test_transport_check_is_not_reached_from_task_check() -> None:
    """Spec: "keep live targets out of task check." `task check` must never run the Docker-backed
    transport suite — only the dedicated, separately-invoked `test:transport` target does."""
    import yaml

    taskfile = yaml.safe_load((Path(__file__).resolve().parents[1] / "Taskfile.yml").read_text())
    assert "test:transport" in taskfile["tasks"], "Taskfile.yml has no test:transport target"

    def reaches(target: str, seen: set[str]) -> bool:
        if target in seen:
            return False
        seen.add(target)
        for cmd in taskfile["tasks"][target].get("cmds", []):
            if (
                isinstance(cmd, dict)
                and "task" in cmd
                and (cmd["task"] == "test:transport" or reaches(cmd["task"], seen))
            ):
                return True
        return False

    assert not reaches("check", set()), "task check must not reach test:transport"
