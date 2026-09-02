"""`packages/billing-connector` is a wired-in workspace member (billing-connector task 1.1).

Same lesson as `test_workspace_scaffold.py` and `test_twenty_projection_scaffold.py`: declared
scope must equal executed scope. A package can exist on disk while lint, typecheck, test, and
coverage each silently skip it, because each has its own path list in `Taskfile.yml`. This gate
pins the wirings so a later edit cannot drop the connector package out of CI while `task check`
stays green.

It also asserts the package is importable, versioned, and typed — the three properties task
1.1 exists to establish before any behavior lands.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import billing_connector
import yaml
from pytest_socket import SocketBlockedError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = "packages/billing-connector"
_MODULE = "billing_connector"


def _root_pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())


def _pkg_pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / _PKG_DIR / "pyproject.toml").read_text())


def _taskfile() -> dict:
    return yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())


def test_package_is_a_workspace_member():
    members = _root_pyproject()["tool"]["uv"]["workspace"]["members"]
    assert _PKG_DIR in members, f"{_PKG_DIR} is not a uv workspace member"
    sources = _root_pyproject()["tool"]["uv"]["sources"]
    assert sources.get("billing-connector") == {"workspace": True}, (
        "billing-connector is missing from [tool.uv.sources] as a workspace source"
    )


def test_package_is_importable_versioned_and_typed():
    """The three properties this task exists to establish, ahead of any behavior."""
    assert billing_connector.__file__ is not None
    pkg_path = Path(billing_connector.__file__).resolve()
    assert pkg_path.parent.name == _MODULE
    assert billing_connector.__version__ == _pkg_pyproject()["project"]["version"], (
        "billing_connector.__version__ does not match the package's pyproject.toml version"
    )
    assert (pkg_path.parent / "py.typed").is_file(), (
        f"{_PKG_DIR} lacks py.typed — downstream imports would go unchecked under strict typing"
    )


def test_package_has_no_connector_import_yet():
    """1.2 wires the credential-posture gate by importing pulse_core.connector; 1.1 must not,
    or the gate would discover a package with no config yet."""
    src = (_REPO_ROOT / _PKG_DIR / "src" / _MODULE / "__init__.py").read_text()
    assert "pulse_core.connector" not in src


def test_package_requires_python_matches_root():
    """The workspace tests 3.10-3.14; a narrower member pin would fracture the lock."""
    assert _pkg_pyproject()["project"]["requires-python"] == _root_pyproject()["project"]["requires-python"]


def test_quality_gates_reach_the_package():
    """LINT_PATHS lints it, TESTED_PATHS runs its suite, COV_PATHS applies the coverage floor."""
    taskfile_vars = _taskfile()["vars"]
    assert _PKG_DIR in taskfile_vars["LINT_PATHS"].split(), f"{_PKG_DIR} missing from LINT_PATHS"
    assert f"{_PKG_DIR}/tests" in taskfile_vars["TESTED_PATHS"].split(), f"{_PKG_DIR}/tests missing from TESTED_PATHS"
    assert f"--cov={_PKG_DIR}/src" in taskfile_vars["COV_PATHS"].split(), f"{_PKG_DIR}/src missing from COV_PATHS"


def test_typecheck_runs_pyright_on_the_package():
    """This package typechecks under pyright strict, same as verdict-relay and schedules."""
    cmds = [cmd for cmd in _taskfile()["tasks"]["typecheck"]["cmds"] if isinstance(cmd, str)]
    assert any(f"pyright -p {_PKG_DIR}" in cmd for cmd in cmds), (
        f"`task typecheck` does not run pyright on {_PKG_DIR} — the package would never typecheck in CI"
    )


def test_ruff_allows_asserts_in_package_tests():
    """The root "tests/*" S101 exemption does not reach `packages/*/tests`."""
    ignores = _root_pyproject()["tool"]["ruff"]["lint"]["per-file-ignores"]
    pattern = f"{_PKG_DIR}/tests/**"
    assert pattern in ignores and "S101" in ignores[pattern], (
        f"ruff per-file-ignores lacks S101 for {pattern} — every pytest assert in it would lint-fail"
    )


def test_package_declares_dev_dependencies():
    """pytest-socket and pyright, per task 1.1: pyright for typecheck, pytest-socket for the
    socket-blocked test harness task 1.4 adds."""
    dev_group = {dep.split(">=")[0].split("==")[0] for dep in _pkg_pyproject()["dependency-groups"]["dev"]}
    assert "pytest-socket" in dev_group
    assert "pyright" in dev_group


def test_package_depends_on_pulse_core_and_billing():
    deps = {dep.split(">=")[0].split("==")[0] for dep in _pkg_pyproject()["project"]["dependencies"]}
    assert "pulse-core" in deps
    assert "billing" in deps
    sources = _pkg_pyproject()["tool"]["uv"]["sources"]
    assert sources.get("pulse-core") == {"workspace": True}
    assert sources.get("billing") == {"workspace": True}


def test_pytest_socket_is_importable():
    """The socket-blocking conftest.py lands in task 1.4; this only proves the dependency
    task 1.1 declares is installed and importable ahead of that."""
    assert SocketBlockedError is not None
