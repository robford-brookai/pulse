"""Gate 3: Configuration Validity.

Every config file parses and satisfies its own native validator, in isolation. Gate 3 asks "is
this file well-formed"; gate 4 asks "do the commands built from it run".

Usage: uv run pytest tests/scaffold/cat3_config_validity.py -v
"""

import json
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml

from ._scaffold import ROOT, requires_task, tomllib

WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))


def test_taskfile_parses() -> None:
    """Parsed directly rather than via `task --list-all` so this holds in CI without go-task."""
    data = yaml.safe_load((ROOT / "Taskfile.yml").read_text())
    assert data["version"] == "3"
    assert data.get("tasks"), "Taskfile.yml declares no tasks"


@requires_task
def test_task_cli_accepts_the_taskfile() -> None:
    r = subprocess.run(
        ["task", "--list-all"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


def test_pyproject_parses_with_required_tables() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for table in ("project", "dependency-groups", "build-system"):
        assert table in data, f"pyproject.toml missing [{table}]"
    assert data["project"]["name"], "pyproject.toml has no project name"


def test_pytest_slow_marker_is_registered() -> None:
    """An unregistered marker makes `-m "not slow"` silently match nothing under strict config."""
    opts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    assert any(m.startswith("slow:") for m in opts["markers"]), "register the `slow` marker"
    assert "not slow" in opts["addopts"], "default run must exclude slow gates"


def test_every_scaffold_gate_is_collectable() -> None:
    """A gate pytest never collects is worse than no gate: the suite passes having run nothing.

    `cat1_structure.py` matches no default `python_files` pattern, so it is only collected when
    named explicitly on the command line — `task test` and CI would skip all nine silently.
    """
    opts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    patterns = opts["python_files"]
    gates = sorted(p.name for p in Path(__file__).parent.glob("cat[0-9]_*.py"))
    assert gates, "no cat*.py gate files found"
    for gate in gates:
        assert any(fnmatch(gate, pattern) for pattern in patterns), (
            f"{gate} matches no python_files pattern in {patterns}; pytest will not collect it"
        )


def test_coverage_floor_is_configured() -> None:
    """In pyproject, not only in a CI flag, so `task test` and tox enforce the same floor."""
    report = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["coverage"]["report"]
    assert report["fail_under"] >= 80, "coverage floor must be at least 80"


def test_claude_settings_allow_the_documented_commands() -> None:
    cfg = json.loads((ROOT / ".claude/settings.json").read_text())
    allow = cfg["permissions"]["allow"]
    assert any(rule.startswith("Bash(task") for rule in allow), (
        ".claude/settings.json should allow `task` — it is the documented entry point"
    )


def test_python_version_is_within_requires_python() -> None:
    pinned = (ROOT / ".python-version").read_text().strip()
    requires = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["requires-python"]
    major, minor = (int(p) for p in pinned.split(".")[:2])
    floor = re.search(r">=\s*(\d+)\.(\d+)", requires)
    assert floor, f"cannot parse requires-python: {requires}"
    assert (major, minor) >= (int(floor.group(1)), int(floor.group(2))), (
        f".python-version {pinned} is below requires-python {requires}"
    )


def test_precommit_config_is_valid() -> None:
    r = subprocess.run(
        ["uv", "run", "pre-commit", "validate-config"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_mcp_json_declares_the_openlore_server() -> None:
    cfg = json.loads((ROOT / ".mcp.json").read_text())
    assert "openlore" in cfg["mcpServers"], ".mcp.json must declare the openlore MCP server"
    assert cfg["mcpServers"]["openlore"]["command"] == "openlore"


def test_openspec_config_is_valid() -> None:
    cfg = yaml.safe_load((ROOT / "openspec/config.yaml").read_text())
    assert cfg["schema"] == "spec-driven"
    assert "context" in cfg, "openspec/config.yaml needs a context block"


def test_mkdocs_config_parses() -> None:
    cfg = yaml.safe_load((ROOT / "mkdocs.yml").read_text())
    assert cfg["site_name"], "mkdocs.yml has no site_name"


def test_workflows_exist() -> None:
    assert WORKFLOWS, ".github/workflows contains no *.yml"


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses(wf: Path) -> None:
    """YAML 1.1 resolves a bare `on:` key to boolean True, so both spellings are accepted."""
    data = yaml.safe_load(wf.read_text())
    assert "jobs" in data, f"{wf.name} declares no jobs"
    assert "on" in data or True in data, f"{wf.name} declares no triggers"
