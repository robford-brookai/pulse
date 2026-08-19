"""`packages/twenty-projection` is a wired-in workspace member (twenty-projection task 1.1).

Same lesson as `test_workspace_scaffold.py`: declared scope must equal executed scope. A
package can exist on disk while lint, typecheck, tests, and coverage each silently skip it,
because each has its own path list in `Taskfile.yml`. This gate pins the wirings so a later
edit cannot drop the projection package out of CI while `task check` stays green.

It also pins the `projection:consume` posture: defined, described, TARGET-required, and —
together with `test_credentialed_twenty_targets_stay_out_of_check` — never reachable from
`check`, same as `twenty:deploy`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = "packages/twenty-projection"
_MODULE = "twenty_projection"


def _root_pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())


def _taskfile() -> dict:
    return yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())


def test_package_is_a_workspace_member():
    members = _root_pyproject()["tool"]["uv"]["workspace"]["members"]
    assert _PKG_DIR in members, f"{_PKG_DIR} is not a uv workspace member"


def test_package_has_src_layout_with_typing_marker():
    """The package ships pyproject, `src/<module>/__init__.py`, `py.typed`, and a tests dir."""
    root = _REPO_ROOT / _PKG_DIR
    assert (root / "pyproject.toml").is_file(), f"{_PKG_DIR}/pyproject.toml missing"
    assert (root / "src" / _MODULE / "__init__.py").is_file(), f"{_PKG_DIR} lacks src/{_MODULE}/__init__.py"
    assert (root / "src" / _MODULE / "py.typed").is_file(), (
        f"{_PKG_DIR} lacks py.typed — downstream imports would go unchecked under strict typing"
    )
    assert (root / "tests").is_dir(), f"{_PKG_DIR}/tests missing"


def test_package_requires_python_matches_root():
    """The workspace tests 3.10-3.14; a narrower member pin would fracture the lock."""
    root_requires = _root_pyproject()["project"]["requires-python"]
    pkg = tomllib.loads((_REPO_ROOT / _PKG_DIR / "pyproject.toml").read_text())
    assert pkg["project"]["requires-python"] == root_requires, f"{_PKG_DIR} requires-python differs from the root"


def test_quality_gates_reach_the_package():
    """LINT_PATHS lints it, TESTED_PATHS runs its suite, COV_PATHS applies the coverage floor."""
    taskfile_vars = _taskfile()["vars"]
    assert _PKG_DIR in taskfile_vars["LINT_PATHS"].split(), f"{_PKG_DIR} missing from LINT_PATHS"
    assert f"{_PKG_DIR}/tests" in taskfile_vars["TESTED_PATHS"].split(), f"{_PKG_DIR}/tests missing from TESTED_PATHS"
    assert f"--cov={_PKG_DIR}/src" in taskfile_vars["COV_PATHS"].split(), f"{_PKG_DIR}/src missing from COV_PATHS"


def test_typecheck_runs_pyright_on_the_package():
    """This package typechecks under pyright strict, same as schedules and consent-ingress."""
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


def test_projection_consume_is_defined_and_requires_target():
    """Credentialed by design: no TARGET, no run — same posture as `twenty:deploy`."""
    tasks = _taskfile()["tasks"]
    assert "projection:consume" in tasks, "Taskfile.yml does not define projection:consume"
    spec = tasks["projection:consume"]
    assert spec.get("desc"), "projection:consume has no desc — it would not appear in the grouped listing"
    assert "TARGET" in (spec.get("requires") or {}).get("vars", []), (
        "projection:consume does not require TARGET — it would run credential-less against nothing"
    )
