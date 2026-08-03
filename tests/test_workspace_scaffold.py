"""`packages/pulse-ledger` and `packages/pulse-core` are wired-in workspace members (DNA-785).

The 1.3/1.4 lesson from the archived change: declared scope must equal executed
scope. A package can exist on disk while every quality gate silently skips it —
lint, typecheck, tests, and coverage each have their own path list in
`Taskfile.yml`, and membership in `[tool.uv.workspace]` implies none of them.
This gate pins all five wirings at once, so a later edit cannot drop a pulse
package out of CI while `task check` stays green.
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

_PACKAGES = {
    "packages/pulse-ledger": "pulse_ledger",
    "packages/pulse-core": "pulse_core",
}


def _root_pyproject() -> dict:
    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())


def _taskfile_vars() -> dict:
    return yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())["vars"]


def test_packages_are_workspace_members():
    members = _root_pyproject()["tool"]["uv"]["workspace"]["members"]
    for pkg_dir in _PACKAGES:
        assert pkg_dir in members, f"{pkg_dir} is not a uv workspace member"


def test_packages_have_src_layout_with_typing_marker():
    """Each package ships pyproject, `src/<module>/__init__.py`, `py.typed`, and a tests dir."""
    for pkg_dir, module in _PACKAGES.items():
        root = _REPO_ROOT / pkg_dir
        assert (root / "pyproject.toml").is_file(), f"{pkg_dir}/pyproject.toml missing"
        assert (root / "src" / module / "__init__.py").is_file(), f"{pkg_dir} lacks src/{module}/__init__.py"
        assert (root / "src" / module / "py.typed").is_file(), (
            f"{pkg_dir} lacks py.typed — mypy runs strict here; an untyped-looking "
            "package would exempt every downstream import from checking."
        )
        assert (root / "tests").is_dir(), f"{pkg_dir}/tests missing"


def test_package_requires_python_matches_root():
    """The workspace tests 3.10-3.14; a narrower member pin would fracture the lock."""
    root_requires = _root_pyproject()["project"]["requires-python"]
    for pkg_dir in _PACKAGES:
        pkg = tomllib.loads((_REPO_ROOT / pkg_dir / "pyproject.toml").read_text())
        assert pkg["project"]["requires-python"] == root_requires, (
            f"{pkg_dir} requires-python differs from the root workspace"
        )


def test_lint_reaches_pulse_packages():
    lint_paths = _taskfile_vars()["LINT_PATHS"].split()
    for pkg_dir in _PACKAGES:
        assert pkg_dir in lint_paths, f"{pkg_dir} missing from LINT_PATHS"


def test_typecheck_reaches_pulse_packages():
    typed_paths = _taskfile_vars()["TYPED_PATHS"].split()
    for pkg_dir in _PACKAGES:
        assert f"{pkg_dir}/src" in typed_paths, f"{pkg_dir}/src missing from TYPED_PATHS"


def test_tests_and_coverage_reach_pulse_packages():
    """TESTED_PATHS runs the suites; COV_PATHS makes the 80% floor apply to the code."""
    taskfile_vars = _taskfile_vars()
    tested_paths = taskfile_vars["TESTED_PATHS"].split()
    cov_paths = taskfile_vars["COV_PATHS"].split()
    for pkg_dir in _PACKAGES:
        assert f"{pkg_dir}/tests" in tested_paths, f"{pkg_dir}/tests missing from TESTED_PATHS"
        assert f"--cov={pkg_dir}/src" in cov_paths, f"{pkg_dir}/src missing from COV_PATHS"


def test_ruff_allows_asserts_in_package_tests():
    """The root "tests/*" S101 exemption does not reach `packages/*/tests` (see the ocean note)."""
    ignores = _root_pyproject()["tool"]["ruff"]["lint"]["per-file-ignores"]
    for pkg_dir in _PACKAGES:
        pattern = f"{pkg_dir}/tests/**"
        assert pattern in ignores and "S101" in ignores[pattern], (
            f"ruff per-file-ignores lacks S101 for {pattern} — every pytest assert in it would lint-fail"
        )
