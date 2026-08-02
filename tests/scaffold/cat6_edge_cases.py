"""Gate 6: Edge Cases & Failure Modes.

Degenerate inputs produce the documented behaviour — a clear non-zero exit or a documented no-op,
never an unhandled traceback.

Usage: uv run pytest tests/scaffold/cat6_edge_cases.py -v
"""

import subprocess
import sys
from pathlib import Path

import pytest

from ._scaffold import ROOT, load_script, template_only

dispatch = load_script("dispatch_tasks.py")
collect = load_script("collect_handoffs.py")

DISPATCH_CLI = ROOT / "scripts/dispatch_tasks.py"
COLLECT_CLI = ROOT / "scripts/collect_handoffs.py"


def run_cli(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def write_change(root: Path, change: str, body: str) -> Path:
    d = root / "openspec/changes" / change
    d.mkdir(parents=True)
    (d / "tasks.md").write_text(body)
    return d


# --- dispatch_tasks CLI ------------------------------------------------------------------------


def test_dispatch_requires_change_argument(tmp_path: Path) -> None:
    r = run_cli(DISPATCH_CLI, cwd=tmp_path)
    assert r.returncode == 2, "argparse must reject a missing --change"
    assert "--change" in r.stderr


def test_dispatch_missing_tasks_md_exits_nonzero(tmp_path: Path) -> None:
    r = run_cli(DISPATCH_CLI, "--change", "nope", cwd=tmp_path)
    assert r.returncode != 0
    assert "not found" in r.stderr, "a missing tasks.md must say so on stderr"


def test_dispatch_empty_tasks_md_is_a_documented_noop(tmp_path: Path) -> None:
    write_change(tmp_path, "empty", "")
    r = run_cli(DISPATCH_CLI, "--change", "empty", cwd=tmp_path)
    assert r.returncode == 0, "an empty tasks.md is a no-op, not a failure"
    assert "No tasks found" in r.stdout


def test_dispatch_header_only_tasks_md_is_a_noop(tmp_path: Path) -> None:
    write_change(tmp_path, "headers", "# Tasks\n\n## Milestone 1\n\n## Milestone 2\n")
    r = run_cli(DISPATCH_CLI, "--change", "headers", "--skip-hardening", cwd=tmp_path)
    assert r.returncode == 0
    assert "No tasks found" in r.stdout


def test_dispatch_honors_output_override(tmp_path: Path) -> None:
    write_change(tmp_path, "c", "- [ ] One task\n")
    r = run_cli(DISPATCH_CLI, "--change", "c", "--output", "custom_dir", "--skip-hardening", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "custom_dir/c/task-001.md").is_file()


def test_dispatch_prints_go_task_var_syntax(tmp_path: Path) -> None:
    """Regression: `task collect --change X` exits 2. The hint must use CHANGE=X."""
    write_change(tmp_path, "c", "- [ ] One task\n")
    r = run_cli(DISPATCH_CLI, "--change", "c", "--skip-hardening", cwd=tmp_path)
    assert "task collect CHANGE=c" in r.stdout
    assert "--change" not in r.stdout, "go-task rejects --change as an unknown flag"


# --- parse_tasks robustness --------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "- not a checkbox",
        "-[ ] missing space before bracket",
        "## Header only",
        "  - [ ] indented task line",
        "- [?] unrecognised marker",
        "",
        "just prose",
    ],
)
def test_malformed_lines_never_raise(tmp_path: Path, line: str) -> None:
    md = tmp_path / "tasks.md"
    md.write_text(line + "\n")
    dispatch.parse_tasks(md)  # must not raise


@pytest.mark.parametrize(
    "title",
    [
        "Ünïcödé täsk with accents",
        "task with  multiple   spaces",
        "task/with/slashes",
        "T" * 300,
        'task with `backticks` and "quotes"',
    ],
)
def test_awkward_titles_still_emit_valid_files(tmp_path: Path, title: str) -> None:
    tasks = [{"milestone": "M", "title": title, "body": [], "done": False}]
    (path,) = dispatch.emit_work_orders(tasks, "c", tmp_path / "out")
    assert path.is_file()
    assert title in path.read_text()


def test_rerun_is_deterministic_and_does_not_duplicate(tmp_path: Path) -> None:
    write_change(tmp_path, "c", "- [ ] One\n- [ ] Two\n")
    first = run_cli(DISPATCH_CLI, "--change", "c", "--skip-hardening", cwd=tmp_path)
    out = tmp_path / "work_orders/c"
    snapshot = {p.name: p.read_text() for p in sorted(out.glob("*.md"))}
    second = run_cli(DISPATCH_CLI, "--change", "c", "--skip-hardening", cwd=tmp_path)
    assert first.returncode == second.returncode == 0
    assert {p.name: p.read_text() for p in sorted(out.glob("*.md"))} == snapshot
    assert len(list(out.glob("*.md"))) == 2, "re-run must overwrite, not accumulate"


# --- collect_handoffs CLI ---------------------------------------------------------------------


def test_collect_requires_change_argument(tmp_path: Path) -> None:
    r = run_cli(COLLECT_CLI, cwd=tmp_path)
    assert r.returncode == 2
    assert "--change" in r.stderr


def test_collect_with_no_worktrees_exits_nonzero(tmp_path: Path) -> None:
    empty = tmp_path / "worktrees"
    empty.mkdir()
    r = run_cli(COLLECT_CLI, "--change", "c", "--worktrees-dir", str(empty), cwd=tmp_path)
    assert r.returncode == 1
    assert "No worktrees found" in r.stdout


def test_collect_with_worktrees_but_no_handoffs_reports_and_succeeds(tmp_path: Path) -> None:
    wt = tmp_path / "worktrees/task-001"
    wt.mkdir(parents=True)
    r = run_cli(COLLECT_CLI, "--change", "c", "--worktrees-dir", str(wt.parent), cwd=tmp_path)
    assert r.returncode == 0
    assert "No HANDOFF.md files found in any worktree." in r.stdout


def test_collect_writes_summary_when_handoffs_exist(tmp_path: Path) -> None:
    wt = tmp_path / "worktrees/task-001"
    wt.mkdir(parents=True)
    (wt / "HANDOFF.md").write_text("# HANDOFF\n")
    r = run_cli(COLLECT_CLI, "--change", "c", "--worktrees-dir", str(wt.parent), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "handoffs/c/SUMMARY.md").is_file()
    assert (tmp_path / "handoffs/c/task-001.md").is_file()


# --- new-repo.sh argument validation ------------------------------------------------------
#
# These must fail before `gh repo create`, or a rejected invocation leaves an orphaned remote
# repository behind. The tests assert on the message rather than only the exit code, because an
# early `${2:?}` failure would also be non-zero while telling the user nothing useful.

NEW_REPO_CLI = ROOT / "new-repo.sh"


def run_new_repo(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(NEW_REPO_CLI), *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("package", "reason"),
    [
        ("pulse-check1", "hyphens are not importable"),
        ("1bad", "cannot start with a digit"),
        ("Bad_Pkg", "uppercase is not a valid package name"),
        ("has space", "whitespace is not a valid package name"),
    ],
)
@template_only
def test_new_repo_rejects_invalid_package_names(package: str, reason: str) -> None:
    result = run_new_repo("pulse-check1", package, "desc")
    assert result.returncode != 0, reason
    assert "Invalid package name" in result.stderr, result.stderr


@template_only
def test_new_repo_rejects_the_templates_own_package() -> None:
    """A no-op rename silently ships a project still named after the template."""
    template_pkg = next(p.name for p in (ROOT / "src").iterdir() if p.is_dir() and not p.name.startswith("__"))
    result = run_new_repo("pulse-check1", template_pkg, "desc")
    assert result.returncode != 0
    assert "template's own package" in result.stderr, result.stderr
    assert "pulse_check1" in result.stderr, "the error should suggest a valid package name"


@template_only
def test_new_repo_rejects_invalid_repo_names() -> None:
    result = run_new_repo("Bad_Name", "pulse_check1", "desc")
    assert result.returncode != 0
    assert "Invalid repo name" in result.stderr, result.stderr


@template_only
def test_new_repo_validates_before_creating_anything() -> None:
    """Every validation branch must sit above the `gh repo create` line, not below it."""
    lines = NEW_REPO_CLI.read_text().splitlines()
    # The literal command, not the comment above it that explains why the order matters.
    create_at = next(i for i, line in enumerate(lines) if line.strip().startswith("gh repo create"))
    for marker in ("Invalid repo name", "Invalid package name", "template's own package"):
        marker_at = next(i for i, line in enumerate(lines) if marker in line and "#" not in line[:2])
        assert marker_at < create_at, (
            f"{marker!r} is checked after `gh repo create` — a rejection would orphan a remote repo"
        )


def test_collect_creates_missing_output_dir(tmp_path: Path) -> None:
    wt = tmp_path / "worktrees/task-001"
    wt.mkdir(parents=True)
    (wt / "HANDOFF.md").write_text("x")
    out = collect.collect_handoffs([wt], "c", tmp_path / "deep/nested/out")
    assert out and out[0].parent.is_dir()
