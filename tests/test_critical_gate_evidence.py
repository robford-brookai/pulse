"""`scripts/critical_gate_evidence.py` — machine-readable evidence for the critical gate, and its
independent validator (task 1.2, `critical-path-verification`).

Three layers, each tested directly: `build_evidence`/`write_evidence` (the JSON shape a run
produces), `validate_evidence` (a second, independent pass over that JSON that re-derives
tested-vs-skipped from the evidence's own counts rather than trusting a stored `ok` flag — the
spec's "Gate receipt distinguishes tested from skipped" scenario), and the CLI (`main`), exercised
end to end via real subprocess pytest runs against small fixture files, the same posture
`tests/test_critical_postgres_gate.py` uses for the gate itself.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, filename: str):
    path = SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Loaded in this order so `critical_gate_evidence`'s own `import critical_pg_gate` resolves to
# the same module object this test uses.
gate = _load("critical_pg_gate", "critical_pg_gate.py")
evidence_mod = _load("critical_gate_evidence", "critical_gate_evidence.py")

CLI_PATH = SCRIPTS_DIR / "critical_gate_evidence.py"

_PASSING_CRITICAL_TEST = """
import pytest

@pytest.mark.critical
def test_invariant_holds():
    assert 1 + 1 == 2
"""

_SKIPPED_CRITICAL_TEST = """
import pytest

@pytest.mark.critical
def test_not_implemented_yet():
    pytest.skip("reversal case not implemented yet")
"""

_NOT_CRITICAL_TEST = """
def test_unrelated():
    assert True
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    test_file = tmp_path / name
    test_file.write_text(body)
    return test_file


def _child_env(tmp_path: Path, *, pg_bindir: Path | None = None) -> dict[str, str]:
    """A subprocess env with no Postgres reachable on PATH, and no PULSE_CRITICAL_PG_MODE
    inherited from whatever is running this test — only `pg_bindir`, if given, is visible."""
    empty_path_dir = tmp_path / "empty-path"
    empty_path_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.pop("PULSE_PG_BINDIR", None)
    env.pop(gate.MODE_ENV_VAR, None)
    env["PATH"] = str(empty_path_dir)
    if pg_bindir is not None:
        env["PULSE_PG_BINDIR"] = str(pg_bindir)
    return env


def _fake_postgres_bindir(tmp_path: Path, version_line: str = "postgres (PostgreSQL) 16.4") -> Path:
    bindir = tmp_path / "pgbin"
    bindir.mkdir()
    for name in gate.PG_BINARIES:
        script = bindir / name
        if name == "postgres":
            script.write_text(f"#!/bin/sh\necho '{version_line}'\nexit 0\n")
        else:
            script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
    return bindir


def _run_cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, our own script
        [sys.executable, str(CLI_PATH), *args], env=env, capture_output=True, text=True, check=False
    )


# --- versions ------------------------------------------------------------------------------


def test_python_version_matches_the_running_interpreter() -> None:
    assert evidence_mod.python_version() == platform.python_version()


def test_postgres_version_is_none_without_a_bindir() -> None:
    assert evidence_mod.postgres_version(None) is None


def test_postgres_version_parses_the_binarys_own_output(tmp_path: Path) -> None:
    bindir = _fake_postgres_bindir(tmp_path, "postgres (PostgreSQL) 16.4")
    assert evidence_mod.postgres_version(bindir) == "16.4"


def test_postgres_version_is_none_when_the_binary_fails(tmp_path: Path) -> None:
    bindir = tmp_path / "pgbin"
    bindir.mkdir()
    script = bindir / "postgres"
    script.write_text("#!/bin/sh\nexit 1\n")
    script.chmod(0o755)
    assert evidence_mod.postgres_version(bindir) is None


# --- build_evidence / write_evidence --------------------------------------------------------


def test_build_evidence_has_exactly_the_required_shape() -> None:
    result = gate.GateResult(
        mode=gate.Mode.REQUIRED,
        ok=True,
        collected=1,
        passed=1,
        skipped=0,
        failed=0,
        errors=0,
        message="1/1 critical tests passed",
    )
    evidence = evidence_mod.build_evidence(
        result,
        commit="deadbeef",
        python_version="3.12.4",
        postgres_version="16.4",
        marker="critical",
        suite_paths=["packages/pulse-ledger/tests"],
        coverage_scopes=[("pulse-ledger", 80), ("pulse-core", 80)],
    )
    assert set(evidence) == evidence_mod.REQUIRED_FIELDS
    assert evidence["mode"] == "required"
    assert evidence["counts"] == {"collected": 1, "passed": 1, "skipped": 0, "failed": 0, "errors": 0}
    assert evidence["versions"] == {"python": "3.12.4", "postgres": "16.4"}
    assert evidence["coverage_scopes"] == [{"name": "pulse-ledger", "floor": 80}, {"name": "pulse-core", "floor": 80}]


def test_write_evidence_round_trips_through_json(tmp_path: Path) -> None:
    result = gate.GateResult(
        mode=gate.Mode.OPTIONAL,
        ok=True,
        collected=0,
        passed=0,
        skipped=0,
        failed=0,
        errors=0,
        message="no critical tests",
    )
    evidence = evidence_mod.build_evidence(
        result,
        commit="abc",
        python_version="3.12.4",
        postgres_version=None,
        marker="critical",
        suite_paths=["tests"],
        coverage_scopes=[("pulse-ledger", 80)],
    )
    path = tmp_path / "nested" / "evidence.json"
    evidence_mod.write_evidence(evidence, path)
    assert json.loads(path.read_text()) == evidence


# --- validate_evidence -----------------------------------------------------------------------


def _good_required_evidence(**overrides: object) -> dict:
    base = {
        "schema_version": 1,
        "commit": "abc123",
        "mode": "required",
        "marker": "critical",
        "suite_paths": ["packages/pulse-ledger/tests"],
        "versions": {"python": "3.12.4", "postgres": "16.4"},
        "counts": {"collected": 6, "passed": 6, "skipped": 0, "failed": 0, "errors": 0},
        "ok": True,
        "message": "6/6 critical tests passed",
        "coverage_scopes": [{"name": "pulse-ledger", "floor": 80}, {"name": "pulse-core", "floor": 80}],
    }
    base.update(overrides)
    return base


def test_validate_evidence_accepts_a_well_formed_required_run() -> None:
    validation = evidence_mod.validate_evidence(_good_required_evidence())
    assert validation.ok is True
    assert validation.reasons == ()


def test_validate_evidence_flags_missing_fields() -> None:
    evidence = _good_required_evidence()
    del evidence["versions"]
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert "versions" in validation.reasons[0]


def test_validate_evidence_flags_zero_collection_even_when_marked_ok() -> None:
    """The independent check `validate_evidence` exists for: a stored `ok=True` never hides an
    empty critical collection from the evidence's own counts."""
    evidence = _good_required_evidence(
        counts={"collected": 0, "passed": 0, "skipped": 0, "failed": 0, "errors": 0}, ok=True
    )
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("zero critical tests collected" in r for r in validation.reasons)
    assert any("claims ok=true" in r for r in validation.reasons)


def test_validate_evidence_flags_a_skipped_case_in_required_mode() -> None:
    evidence = _good_required_evidence(
        counts={"collected": 6, "passed": 5, "skipped": 1, "failed": 0, "errors": 0}, ok=False
    )
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("skipped" in r for r in validation.reasons)


def test_validate_evidence_allows_skips_reported_in_optional_mode() -> None:
    evidence = _good_required_evidence(
        mode="optional", counts={"collected": 6, "passed": 5, "skipped": 1, "failed": 0, "errors": 0}
    )
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is True


def test_validate_evidence_flags_a_missing_postgres_version_in_required_mode() -> None:
    evidence = _good_required_evidence(versions={"python": "3.12.4", "postgres": None})
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("Postgres version" in r for r in validation.reasons)


def test_validate_evidence_does_not_require_a_postgres_version_in_optional_mode() -> None:
    evidence = _good_required_evidence(mode="optional", versions={"python": "3.12.4", "postgres": None})
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is True


def test_validate_evidence_flags_failures_and_errors() -> None:
    evidence = _good_required_evidence(
        counts={"collected": 6, "passed": 4, "skipped": 0, "failed": 1, "errors": 1}, ok=False
    )
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("failed" in r and "errored" in r for r in validation.reasons)


@pytest.mark.parametrize(
    "overrides",
    [
        {"message": "run leaked a SECRET value"},
        {"versions": {"python": "3.12.4", "postgres": "token-abc123"}},
    ],
)
def test_validate_evidence_flags_forbidden_terms_wherever_nested(overrides: dict) -> None:
    evidence = _good_required_evidence(**overrides)
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("forbidden term" in r for r in validation.reasons)


# --- CLI (main) end to end ---------------------------------------------------------------------


def test_cli_writes_evidence_for_a_passing_required_suite(tmp_path: Path) -> None:
    """GIVEN the pinned Postgres prerequisite is available WHEN the critical suites execute THEN
    they run and identify its version in the evidence."""
    test_file = _write(tmp_path, "test_passing.py", _PASSING_CRITICAL_TEST)
    bindir = _fake_postgres_bindir(tmp_path)
    evidence_out = tmp_path / "evidence.json"
    junit_out = tmp_path / "suite.xml"
    result = _run_cli(
        [
            str(test_file),
            "--mode",
            "required",
            "--commit",
            "deadbeef",
            "--evidence-out",
            str(evidence_out),
            "--junit-out",
            str(junit_out),
        ],
        env=_child_env(tmp_path, pg_bindir=bindir),
    )
    assert result.returncode == 0, result.stderr
    assert junit_out.exists()
    evidence = json.loads(evidence_out.read_text())
    assert evidence["ok"] is True
    assert evidence["mode"] == "required"
    assert evidence["commit"] == "deadbeef"
    assert evidence["counts"] == {"collected": 1, "passed": 1, "skipped": 0, "failed": 0, "errors": 0}
    assert evidence["versions"]["postgres"] == "16.4"
    assert evidence_mod.validate_evidence(evidence).ok is True


def test_cli_writes_evidence_even_when_required_mode_fails_on_a_skip(tmp_path: Path) -> None:
    """A failing run's evidence must not disappear — it is the run whose receipt matters most."""
    test_file = _write(tmp_path, "test_skipped.py", _SKIPPED_CRITICAL_TEST)
    evidence_out = tmp_path / "evidence.json"
    result = _run_cli(
        [
            str(test_file),
            "--mode",
            "required",
            "--evidence-out",
            str(evidence_out),
            "--junit-out",
            str(tmp_path / "s.xml"),
        ],
        env=_child_env(tmp_path),
    )
    assert result.returncode == 1
    evidence = json.loads(evidence_out.read_text())
    assert evidence["ok"] is False
    assert evidence["counts"]["skipped"] == 1
    assert "skipped" in evidence["message"]
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("skipped" in r for r in validation.reasons)


def test_cli_flags_zero_collection_in_required_mode(tmp_path: Path) -> None:
    """GIVEN a selector collects zero required tests WHEN evidence is generated THEN the receipt
    identifies the missing invariant coverage rather than reporting a bare pass."""
    test_file = _write(tmp_path, "test_unrelated.py", _NOT_CRITICAL_TEST)
    evidence_out = tmp_path / "evidence.json"
    result = _run_cli(
        [
            str(test_file),
            "--mode",
            "required",
            "--evidence-out",
            str(evidence_out),
            "--junit-out",
            str(tmp_path / "s.xml"),
        ],
        env=_child_env(tmp_path),
    )
    assert result.returncode == 1
    evidence = json.loads(evidence_out.read_text())
    assert evidence["counts"]["collected"] == 0
    validation = evidence_mod.validate_evidence(evidence)
    assert validation.ok is False
    assert any("zero critical tests collected" in r for r in validation.reasons)


def test_cli_optional_mode_passes_without_a_postgres_version(tmp_path: Path) -> None:
    test_file = _write(tmp_path, "test_passing.py", _PASSING_CRITICAL_TEST)
    evidence_out = tmp_path / "evidence.json"
    result = _run_cli(
        [
            str(test_file),
            "--mode",
            "optional",
            "--evidence-out",
            str(evidence_out),
            "--junit-out",
            str(tmp_path / "s.xml"),
        ],
        env=_child_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(evidence_out.read_text())
    assert evidence["versions"]["postgres"] is None
    assert evidence_mod.validate_evidence(evidence).ok is True


# --- CLI argument parsing ------------------------------------------------------------------


def test_parse_coverage_scope_accepts_name_colon_floor() -> None:
    assert evidence_mod._parse_coverage_scope("pulse-ledger:80") == ("pulse-ledger", 80)


def test_parse_coverage_scope_rejects_a_missing_floor() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        evidence_mod._parse_coverage_scope("pulse-ledger")


def test_parse_coverage_scope_rejects_a_non_integer_floor() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        evidence_mod._parse_coverage_scope("pulse-ledger:eighty")
