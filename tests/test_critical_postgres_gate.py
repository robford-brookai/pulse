"""`scripts/critical_pg_gate.py` — the required-Postgres fixture mode and the critical-suite
selector built on it (task 1.1, `critical-path-verification`).

The three required-mode failure paths from the spec's scenarios are exercised end to end with a
real subprocess pytest run against a small fixture test file, not asserted from YAML: a missing
server binary, zero critical collection, and a skipped mandatory case each fail required mode and
name the reason. Optional local mode keeps working — the same missing binary is a visible skip,
not a failure. No real Postgres server is started; discovery is hidden by clearing PATH and the
`PULSE_PG_BINDIR` override in the child environment.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "critical_pg_gate.py"
spec = importlib.util.spec_from_file_location("critical_pg_gate", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)

_NEEDS_PG_TEST = """
import os
import pytest
from critical_pg_gate import Mode, ensure_pg_binaries

@pytest.mark.critical
def test_needs_pg():
    ensure_pg_binaries(Mode(os.environ["PULSE_CRITICAL_PG_MODE"]))
"""

_NOT_CRITICAL_TEST = """
def test_unrelated():
    assert True
"""

_SKIPPED_CRITICAL_TEST = """
import pytest

@pytest.mark.critical
def test_not_implemented_yet():
    pytest.skip("reversal case not implemented yet")
"""

_PASSING_CRITICAL_TEST = """
import pytest

@pytest.mark.critical
def test_invariant_holds():
    assert 1 + 1 == 2
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    test_file = tmp_path / name
    test_file.write_text(body)
    return test_file


def _env_hiding_pg_binaries(tmp_path: Path) -> dict[str, str]:
    """A child env with no Postgres binaries reachable and the gate module importable."""
    empty_path_dir = tmp_path / "empty-path"
    empty_path_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.pop(gate.BINDIR_ENV_VAR, None)
    env["PATH"] = str(empty_path_dir)
    env["PYTHONPATH"] = str(SCRIPT_PATH.parent)
    return env


def _env_with_gate_importable() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPT_PATH.parent)
    return env


def test_help_exits_zero() -> None:
    completed = subprocess.run(  # noqa: S603 — fixed argv, our own script
        [sys.executable, str(SCRIPT_PATH), "--help"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    assert "critical" in completed.stdout


def test_missing_binary_fails_required_mode(tmp_path: Path) -> None:
    """GIVEN a subprocess fixture hides a required Postgres binary WHEN required mode runs THEN
    setup fails rather than passing with a skipped database test."""
    test_file = _write(tmp_path, "test_needs_pg.py", _NEEDS_PG_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.REQUIRED, env=_env_hiding_pg_binaries(tmp_path))
    assert result.ok is False
    assert result.skipped == 0
    assert "no server binaries found" in result.message or result.failed or result.errors


def test_missing_binary_reports_visibly_in_optional_mode(tmp_path: Path) -> None:
    """The same missing binary is a visible skip, not a failure, in optional mode."""
    test_file = _write(tmp_path, "test_needs_pg.py", _NEEDS_PG_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.OPTIONAL, env=_env_hiding_pg_binaries(tmp_path))
    assert result.ok is True
    assert result.skipped == 1
    assert "no server binaries found" in result.message


def test_zero_critical_collection_fails_required_mode(tmp_path: Path) -> None:
    """GIVEN a selector collects zero required tests WHEN the critical gate evaluates suite
    results THEN the gate fails and identifies the missing invariant coverage."""
    test_file = _write(tmp_path, "test_unrelated.py", _NOT_CRITICAL_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is False
    assert result.collected == 0
    assert "no critical tests were collected" in result.message


def test_zero_critical_collection_is_not_penalized_in_optional_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_unrelated.py", _NOT_CRITICAL_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.OPTIONAL, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.collected == 0


def test_skipped_mandatory_case_fails_required_mode(tmp_path: Path) -> None:
    """GIVEN a selector marks a required case skipped WHEN the critical gate evaluates suite
    results THEN the gate fails and identifies the missing invariant coverage."""
    test_file = _write(tmp_path, "test_skipped.py", _SKIPPED_CRITICAL_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is False
    assert result.skipped == 1
    assert "required case(s) skipped" in result.message
    assert "reversal case not implemented yet" in result.message


def test_skipped_mandatory_case_is_visible_but_ok_in_optional_mode(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_skipped.py", _SKIPPED_CRITICAL_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.OPTIONAL, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.skipped == 1
    assert "reversal case not implemented yet" in result.message


def test_passing_critical_suite_succeeds_in_required_mode(tmp_path: Path) -> None:
    """GIVEN the pinned Postgres prerequisite is available (no binaries needed for this fixture)
    WHEN the critical suites execute THEN they run and the gate reports them passed."""
    test_file = _write(tmp_path, "test_passing.py", _PASSING_CRITICAL_TEST)
    result = gate.run_critical_suite([test_file], gate.Mode.REQUIRED, env=_env_with_gate_importable())
    assert result.ok is True
    assert result.collected == 1
    assert result.passed == 1
    assert result.skipped == 0


class TestFindPgBindir:
    def test_returns_none_when_nothing_on_path(self, tmp_path: Path) -> None:
        env = {"PATH": str(tmp_path)}
        assert gate.find_pg_bindir(env=env) is None

    def test_finds_binaries_via_override_env_var(self, tmp_path: Path) -> None:
        for name in gate.PG_BINARIES:
            (tmp_path / name).write_text("#!/bin/sh\n")
            (tmp_path / name).chmod(0o755)
        env = {gate.BINDIR_ENV_VAR: str(tmp_path), "PATH": ""}
        assert gate.find_pg_bindir(env=env) == tmp_path

    def test_rejects_override_dir_missing_a_binary(self, tmp_path: Path) -> None:
        (tmp_path / "initdb").write_text("#!/bin/sh\n")
        env = {gate.BINDIR_ENV_VAR: str(tmp_path), "PATH": ""}
        assert gate.find_pg_bindir(env=env) is None


def test_ensure_pg_binaries_fails_setup_in_required_mode(tmp_path: Path) -> None:
    env = {"PATH": str(tmp_path)}
    with pytest.raises(pytest.fail.Exception):
        gate.ensure_pg_binaries(gate.Mode.REQUIRED, env=env)


def test_ensure_pg_binaries_skips_in_optional_mode(tmp_path: Path) -> None:
    env = {"PATH": str(tmp_path)}
    with pytest.raises(pytest.skip.Exception):
        gate.ensure_pg_binaries(gate.Mode.OPTIONAL, env=env)


def test_run_critical_suite_reports_failure_when_evidence_is_never_produced() -> None:
    """A crashed collection (bad path) must not read as a silent pass."""
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "does-not-exist"
        result = gate.run_critical_suite(
            [missing], gate.Mode.REQUIRED, python=sys.executable, env=_env_with_gate_importable()
        )
        assert result.ok is False
