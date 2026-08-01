"""Gate 9: End-to-End Golden Workflow.

The documented daily loop — dispatch, then collect — run against committed fixtures and compared
to known-good output.

Usage: uv run pytest tests/scaffold/cat9_golden_workflow.py -v
       uv run pytest tests/scaffold/cat9_golden_workflow.py -m slow -v   # fresh-clone smoke

Regenerating goldens is deliberate and never automatic:
       REGEN=1 uv run pytest tests/scaffold/cat9_golden_workflow.py

Fixtures carry .fixture / .golden suffixes rather than .md so that a markdown-hygiene hook cannot
mistake test data for stray documentation. The dispatch script only ever sees a real `tasks.md`,
which the test materialises in a temp directory.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from ._scaffold import DATA, ROOT, have, requires_task

DISPATCH_CLI = ROOT / "scripts/dispatch_tasks.py"
COLLECT_CLI = ROOT / "scripts/collect_handoffs.py"
FIXTURE_TASKS = DATA / "fixture-change/tasks.md.fixture"
GOLDEN_WORK_ORDERS = DATA / "golden-work-orders"
GOLDEN_SUMMARY = DATA / "golden-collect/SUMMARY.golden"
CHANGE = "fixture-change"
REGEN = bool(os.environ.get("REGEN"))


def stage_change(workdir: Path) -> None:
    dest = workdir / "openspec/changes" / CHANGE
    dest.mkdir(parents=True)
    (dest / "tasks.md").write_text(FIXTURE_TASKS.read_text())


def run_dispatch(workdir: Path) -> list[Path]:
    stage_change(workdir)
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(DISPATCH_CLI), "--change", CHANGE],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return sorted((workdir / "work_orders" / CHANGE).glob("*.md"))


def run_collect(workdir: Path, worktrees: Mapping[str, str | None]) -> Path:
    """Build a worktree layout, collect from it, and return the SUMMARY path."""
    wt_root = workdir / "worktrees"
    for name, handoff in worktrees.items():
        wt = wt_root / name
        wt.mkdir(parents=True)
        if handoff is not None:
            (wt / "HANDOFF.md").write_text(handoff)
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(COLLECT_CLI), "--change", CHANGE, "--worktrees-dir", str(wt_root)],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return workdir / "handoffs" / CHANGE / "SUMMARY.md"


def normalize(text: str, workdir: Path) -> str:
    """summarize_handoffs embeds absolute paths, which are machine-specific."""
    return text.replace(str(workdir), "<WORKDIR>")


# --- golden dispatch ---------------------------------------------------------------------------


def test_dispatch_matches_golden(tmp_path: Path) -> None:
    emitted = run_dispatch(tmp_path)
    if REGEN:
        shutil.rmtree(GOLDEN_WORK_ORDERS, ignore_errors=True)
        GOLDEN_WORK_ORDERS.mkdir(parents=True)
        for p in emitted:
            (GOLDEN_WORK_ORDERS / f"{p.name}.golden").write_text(p.read_text())
        pytest.skip(f"regenerated {len(emitted)} goldens in {GOLDEN_WORK_ORDERS}")

    goldens = sorted(GOLDEN_WORK_ORDERS.glob("*.golden"))
    assert goldens, f"no goldens committed; run REGEN=1 pytest {Path(__file__).name}"
    assert [p.name for p in emitted] == [g.name.removesuffix(".golden") for g in goldens]
    for emitted_path, golden in zip(emitted, goldens, strict=True):
        assert emitted_path.read_text() == golden.read_text(), f"{emitted_path.name} drifted"


def test_dispatch_emits_one_work_order_per_task(tmp_path: Path) -> None:
    """The fixture has 4 task lines across 2 milestones, including one already done."""
    assert len(run_dispatch(tmp_path)) == 4


def test_dispatch_is_deterministic(tmp_path_factory: pytest.TempPathFactory) -> None:
    a = run_dispatch(tmp_path_factory.mktemp("run_a"))
    b = run_dispatch(tmp_path_factory.mktemp("run_b"))
    assert [p.read_text() for p in a] == [p.read_text() for p in b]


# --- golden collect ---------------------------------------------------------------------------


def test_collect_matches_golden(tmp_path: Path) -> None:
    summary = run_collect(
        tmp_path,
        {
            "task-001": "# HANDOFF\n\n## Spec Updates\n\nNone.\n",
            "task-002": "# HANDOFF\n\n## Design Drift\n\nThe spec omits clock skew.\n",
            "task-003": None,
        },
    )
    actual = normalize(summary.read_text(), tmp_path)
    if REGEN:
        GOLDEN_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_SUMMARY.write_text(actual)
        pytest.skip(f"regenerated {GOLDEN_SUMMARY}")

    assert GOLDEN_SUMMARY.is_file(), f"no golden committed; run REGEN=1 pytest {Path(__file__).name}"
    assert actual == GOLDEN_SUMMARY.read_text()


def test_collect_ordering_is_deterministic(tmp_path_factory: pytest.TempPathFactory) -> None:
    """collect_handoffs sorts worktrees; unsorted iterdir() made SUMMARY order machine-dependent."""
    layout = {"task-003": "# HANDOFF\n", "task-001": "# HANDOFF\n", "task-002": "# HANDOFF\n"}
    a = run_collect(tmp_path_factory.mktemp("collect_a"), layout)
    b = run_collect(tmp_path_factory.mktemp("collect_b"), layout)
    listing = [line for line in a.read_text().splitlines() if line.startswith("- [")]
    assert listing == sorted(listing), f"SUMMARY listing is not sorted: {listing}"
    assert normalize(a.read_text(), a.parents[2]) == normalize(b.read_text(), b.parents[2])


def test_collect_skips_worktrees_without_a_handoff(tmp_path: Path) -> None:
    summary = run_collect(tmp_path, {"task-001": "# HANDOFF\n", "task-002": None})
    collected = sorted(p.name for p in summary.parent.glob("*.md") if p.name != "SUMMARY.md")
    assert collected == ["task-001.md"]


# --- fresh-clone smoke ------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=gate@test.invalid", "-c", "user.name=Gate", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _export_head(dest: Path) -> None:
    """Committed tree only, plus the working-tree sync script so the test covers current code."""
    archive = subprocess.run(
        ["git", "archive", "HEAD"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        ["tar", "-x", "-C", str(dest)],  # noqa: S607
        input=archive.stdout,
        check=True,
    )
    shutil.copy(ROOT / "scripts/template_sync.sh", dest / "scripts/template_sync.sh")


def _rename_package(repo: Path, old: str, new: str) -> None:
    """What bootstrap.sh does on generation."""
    (repo / "src" / old).rename(repo / "src" / new)
    suffixes = {".py", ".yml", ".yaml", ".toml", ".md", ".json", ".sh"}
    for path in repo.rglob("*"):
        if path.is_file() and path.suffix in suffixes:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if old in text:
                path.write_text(text.replace(old, new))


@pytest.mark.slow
def test_template_sync_survives_the_package_rename(tmp_path: Path) -> None:
    """An upstream change touching the package name must land under the LOCAL package name.

    A raw text diff cannot know `pkg_pulse` is a variable: before template_sync.sh rewrote the
    patch, this scenario conflicted and, resolved toward upstream, wrote `src/pkg_pulse/...` into
    a repo whose package is named something else. That is the one thing copier gets for free by
    re-rendering from recorded answers.
    """
    local_slug = "demo_pkg"
    template_slug = next(p.name for p in (ROOT / "src").iterdir() if p.is_dir() and not p.name.startswith("__"))

    upstream, downstream = tmp_path / "upstream", tmp_path / "downstream"
    for d in (upstream, downstream):
        d.mkdir()
        _export_head(d)
        _git("init", "-q", cwd=d)
        _git("add", "-A", cwd=d)
        _git("commit", "-qm", "base", cwd=d)

    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=upstream,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # An upstream improvement that mentions the package — the case that used to break.
    cat1 = upstream / "tests/scaffold/cat1_structure.py"
    cat1.write_text(
        cat1.read_text().replace(
            f'"src/{template_slug}/py.typed",',
            f'"src/{template_slug}/py.typed",\n    "src/{template_slug}/newmod.py",',
        )
    )
    _git("add", "-A", cwd=upstream)
    _git("commit", "-qm", "upstream change touching the package name", cwd=upstream)

    _rename_package(downstream, template_slug, local_slug)
    _git("add", "-A", cwd=downstream)
    _git("commit", "-qm", "bootstrap rename", cwd=downstream)
    (downstream / ".ade-template-version").write_text(base + "\n")

    result = subprocess.run(
        ["bash", "scripts/template_sync.sh", "apply"],  # noqa: S607
        cwd=downstream,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_TEMPLATE_URL": str(upstream)},
    )
    assert result.returncode == 0, f"sync failed:\n{result.stdout}\n{result.stderr}"

    synced = (downstream / "tests/scaffold/cat1_structure.py").read_text()
    assert f'"src/{local_slug}/newmod.py"' in synced, "the upstream addition did not land under the local package name"
    assert template_slug not in synced, (
        f"the template's package name {template_slug} leaked into a repo named {local_slug}"
    )
    assert "<<<<<<<" not in synced, "sync left conflict markers"


@pytest.mark.slow
@requires_task
@pytest.mark.skipif(not have("uv"), reason="uv not installed")
def test_fresh_clone_passes_its_own_gates(tmp_path: Path) -> None:
    """The end-to-end claim: a clone of the committed tree passes the scaffold suite.

    `task test` inherits the `-m "not slow"` default from pyproject.toml, so the clone does not
    re-enter this test and recurse.
    """
    clone = tmp_path / "clone"
    # This process runs inside the host venv; leaving VIRTUAL_ENV set makes uv warn that it does
    # not match the clone's own environment.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    subprocess.run(  # noqa: S603
        ["git", "clone", "-q", str(ROOT), str(clone)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["uv", "sync", "--frozen", "--quiet"],  # noqa: S607
        cwd=clone,
        check=True,
        capture_output=True,
        env=env,
    )
    r = subprocess.run(
        ["task", "test"],  # noqa: S607
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert r.returncode == 0, f"fresh clone failed its own gates:\n{r.stdout}\n{r.stderr}"
