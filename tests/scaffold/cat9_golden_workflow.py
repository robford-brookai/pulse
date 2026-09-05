"""Gate 9: End-to-End Golden Workflow.

The documented daily loop — dispatch, then collect — plus the connector scaffold render, run
against committed fixtures and compared to known-good output.

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
CONNECTOR_CLI = ROOT / "scripts/connector_new.py"
FIXTURE_TASKS = DATA / "fixture-change/tasks.md.fixture"
GOLDEN_WORK_ORDERS = DATA / "golden-work-orders"
GOLDEN_SUMMARY = DATA / "golden-collect/SUMMARY.golden"
GOLDEN_CONNECTOR = DATA / "golden-connector"
GOLDEN_CONNECTOR_NAME = "example-connector"
#: One golden tree per direction. Outbound is the base template; inbound is the base with
#: `templates/connector/direction/inbound/` laid over it (devex-eight-2 task 3.1).
GOLDEN_CONNECTOR_DIRS = {"outbound": GOLDEN_CONNECTOR, "inbound": DATA / "golden-connector-inbound"}
DIRECTIONS = tuple(GOLDEN_CONNECTOR_DIRS)
CHANGE = "fixture-change"
REGEN = bool(os.environ.get("REGEN"))


def stage_change(workdir: Path) -> None:
    dest = workdir / "openspec/changes" / CHANGE
    dest.mkdir(parents=True)
    (dest / "tasks.md").write_text(FIXTURE_TASKS.read_text())


def run_dispatch(workdir: Path) -> list[Path]:
    stage_change(workdir)
    # --skip-hardening: these tests exercise work-order emission, not release. the hardening gate gates
    # releasing worktrees onto a workstation, which a fixture in a temp directory never does.
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(DISPATCH_CLI), "--change", CHANGE, "--skip-hardening"],
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


# --- golden connector scaffold ------------------------------------------------------------------


def render_connector(dest_parent: Path, name: str = GOLDEN_CONNECTOR_NAME, direction: str = "outbound") -> Path:
    """Render templates/connector/ into a temp directory and return the package root."""
    dest = dest_parent / name
    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(CONNECTOR_CLI),
            "--name",
            name,
            "--direction",
            direction,
            "--dest",
            str(dest),
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return dest


def rendered_paths(package: Path) -> list[str]:
    """Every rendered file, as sorted repo-relative strings — sorted because it reaches asserts."""
    return sorted(str(p.relative_to(package)) for p in package.rglob("*") if p.is_file())


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_connector_render_matches_golden(tmp_path: Path, direction: str) -> None:
    golden_dir = GOLDEN_CONNECTOR_DIRS[direction]
    package = render_connector(tmp_path, direction=direction)
    emitted = rendered_paths(package)
    if REGEN:
        shutil.rmtree(golden_dir, ignore_errors=True)
        for relative in emitted:
            golden = golden_dir / f"{relative}.golden"
            golden.parent.mkdir(parents=True, exist_ok=True)
            golden.write_text((package / relative).read_text())
        pytest.skip(f"regenerated {len(emitted)} goldens in {golden_dir}")

    goldens = sorted(str(p.relative_to(golden_dir)).removesuffix(".golden") for p in golden_dir.rglob("*.golden"))
    assert goldens, f"no goldens committed; run REGEN=1 pytest {Path(__file__).name}"
    assert emitted == goldens
    for relative in emitted:
        actual = (package / relative).read_text()
        expected = (golden_dir / f"{relative}.golden").read_text()
        assert actual == expected, f"{relative} drifted from its golden"


def test_the_two_directions_render_different_services(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The overlay replaces whole files, and leaves the ones it does not ship alone."""
    outbound = render_connector(tmp_path_factory.mktemp("outbound"), direction="outbound")
    inbound = render_connector(tmp_path_factory.mktemp("inbound"), direction="inbound")

    service = f"src/{GOLDEN_CONNECTOR_NAME.replace('-', '_')}/service.py"
    assert (outbound / service).read_text() != (inbound / service).read_text()
    # The inbound service stands on the kit's inbound read contract, per the connector-kit spec.
    assert "RowSource" in (inbound / service).read_text()
    assert "CursorStore" in (inbound / service).read_text()
    # conftest.py ships in the base tree only; both directions get the same socket-blocked posture.
    assert (outbound / "tests/conftest.py").read_text() == (inbound / "tests/conftest.py").read_text()
    # Only the base tree renders: no overlay directory leaks into a rendered package.
    assert not any(p.startswith("direction/") for p in rendered_paths(outbound) + rendered_paths(inbound))


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_connector_render_is_deterministic(tmp_path_factory: pytest.TempPathFactory, direction: str) -> None:
    a = render_connector(tmp_path_factory.mktemp("connector_a"), direction=direction)
    b = render_connector(tmp_path_factory.mktemp("connector_b"), direction=direction)
    assert rendered_paths(a) == rendered_paths(b)
    assert [(a / p).read_text() for p in rendered_paths(a)] == [(b / p).read_text() for p in rendered_paths(b)]


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_rendered_connector_package_tests_pass(tmp_path: Path, direction: str) -> None:
    """The scaffold ships a green test, not a stub the developer has to repair first.

    Run from the rendered package so pytest reads *its* pyproject.toml, not the repo root's:
    the point is that the package stands on its own.
    """
    package = render_connector(tmp_path, direction=direction)
    env = {
        **os.environ,
        "PYTHONPATH": str(package / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # Built as a variable rather than inline: the two ruff versions in play (the venv's and the
    # one .pre-commit-config.yaml pins) disagree about whether an inline literal argv triggers
    # S603, and one of them then strips the noqa the other needs.
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    r = subprocess.run(  # noqa: S603
        command,
        cwd=package,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_rendered_connector_leaves_no_unsubstituted_tokens(tmp_path: Path, direction: str) -> None:
    package = render_connector(tmp_path, direction=direction)
    leftover = [p for p in rendered_paths(package) if "{{" in (package / p).read_text()]
    assert leftover == [], f"template tokens survived the render in {leftover}"


def test_connector_new_rejects_an_unusable_name(tmp_path: Path) -> None:
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CONNECTOR_CLI), "--name", "Claims Connector", "--dest", str(tmp_path / "x")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "claims-connector" in r.stderr, r.stderr


def test_connector_new_refuses_an_occupied_destination(tmp_path: Path) -> None:
    package = render_connector(tmp_path)
    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(CONNECTOR_CLI),
            "--name",
            GOLDEN_CONNECTOR_NAME,
            "--dest",
            str(package),
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "already exists" in r.stderr, r.stderr


# --- the registration diff ----------------------------------------------------------------------

#: The Taskfile path variables the diff must extend, and what each must gain.
TASKFILE_VARS = {
    "LINT_PATHS": "packages/claims-connector",
    "TYPED_PATHS": "packages/claims-connector/src",
    "TESTED_PATHS": "packages/claims-connector/tests",
    "COV_PATHS": "--cov=packages/claims-connector/src",
}


#: The files the registration diff edits. `task connector:new` (task 1.4) is what applies it.
REGISTERED_FILES = ("pyproject.toml", "Taskfile.yml")


def print_registrations(name: str) -> str:
    """Run the script in report-only mode and return what it printed."""
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(CONNECTOR_CLI), "--name", name, "--root", str(ROOT), "--print-registrations"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def added_lines(diff: str) -> list[str]:
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


def test_registration_diff_names_every_site() -> None:
    """A scaffolded package is useless until every site names it; the diff is that list."""
    diff = print_registrations("claims-connector")

    assert "--- a/pyproject.toml" in diff
    assert "--- a/Taskfile.yml" in diff
    added = added_lines(diff)

    assert '    "packages/claims-connector",' in added
    assert "claims-connector = { workspace = true }" in added
    assert '"packages/claims-connector/tests/**" = ["S101"]' in added

    for var, addition in TASKFILE_VARS.items():
        line = next((a for a in added if a.startswith(f"  {var}:")), None)
        assert line is not None, f"{var} is not in the diff"
        assert line.endswith(f" {addition}"), line

    assert "  # claims-connector:image:" in added
    assert "  # claims-connector:deploy:" in added


def test_registration_diff_applies_cleanly_and_is_idempotent(tmp_path: Path) -> None:
    """The printed diff is a real patch, and a second run of the script has nothing left to say.

    Both halves matter. A diff that does not apply is a diff a developer has to hand-translate,
    which is the DX cost the scaffold exists to remove; a diff that reapplies would register the
    same package twice.
    """
    for relative in REGISTERED_FILES:
        (tmp_path / relative).write_text((ROOT / relative).read_text())
    patch = tmp_path / "registrations.patch"
    patch.write_text(print_registrations("claims-connector"))

    applied = subprocess.run(  # noqa: S603
        ["git", "apply", "-p1", str(patch)],  # noqa: S607
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr

    rerun = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(CONNECTOR_CLI),
            "--name",
            "claims-connector",
            "--root",
            str(tmp_path),
            "--print-registrations",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rerun.returncode == 0, rerun.stderr
    assert rerun.stdout == "", rerun.stdout


def test_registration_diff_is_printed_but_not_applied(tmp_path: Path) -> None:
    """1.3 renders and reports; `task connector:new` (1.4) is what edits the repo."""
    before = {relative: (ROOT / relative).read_text() for relative in REGISTERED_FILES}
    render_connector(tmp_path)
    after = {relative: (ROOT / relative).read_text() for relative in before}
    assert after == before


def test_connector_new_apply_registrations_names_every_site(tmp_path: Path) -> None:
    """A dry-run render into a tmp copy: `--apply-registrations` is what `task connector:new` runs."""
    for relative in REGISTERED_FILES:
        (tmp_path / relative).write_text((ROOT / relative).read_text())

    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(CONNECTOR_CLI),
            "--name",
            "claims-connector",
            "--dest",
            str(tmp_path / "packages" / "claims-connector"),
            "--template",
            str(ROOT / "templates/connector"),
            "--root",
            str(tmp_path),
            "--apply-registrations",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr

    for relative in REGISTERED_FILES:
        assert "claims-connector" in (tmp_path / relative).read_text(), relative

    # A second run has nothing left to say: applying does not register the package twice.
    rerun = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(CONNECTOR_CLI),
            "--name",
            "claims-connector",
            "--root",
            str(tmp_path),
            "--print-registrations",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rerun.returncode == 0, rerun.stderr
    assert rerun.stdout == "", rerun.stdout


# --- fresh-clone smoke ------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> None:
    """Run git sandboxed against the operator's global config.

    `commit.gpgsign=false` and a neutral `gpg.format` stop a global signing config (a real key,
    or an `ssh`/`x509` format with no matching key) from turning a fixture commit into a signing
    failure. A failure here is re-raised with `exc.stderr` — `capture_output` alone hides it
    behind a bare `CalledProcessError`, which is illegible in a sandbox where the git binary and
    its config are not what the traceback's reader expects.
    """
    cmd = [
        "git",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "gpg.format=openpgp",
        "-c",
        "user.email=gate@test.invalid",
        "-c",
        "user.name=Gate",
        *args,
    ]
    try:
        subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{exc.stderr}") from exc  # noqa: TRY003


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


@pytest.mark.slow
@requires_task
@pytest.mark.skipif(not have("uv"), reason="uv not installed")
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_task_check_green_with_a_scaffolded_connector(tmp_path: Path, direction: str) -> None:
    """`task connector:new` (1.4) registers a package that then passes `task check`, unmodified.

    A scaffolded package that only renders cleanly but breaks lint, typecheck, or docs the moment
    it is registered would be a worse scaffold than none — the whole point of automating the
    eight registrations is that what comes out the other end is already green. Both directions:
    the inbound overlay ships its own service and tests, and they are held to the same bar.
    """
    clone = tmp_path / "clone"
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

    # Built as a variable rather than inline for the reason documented on
    # `test_rendered_connector_package_tests_pass`: the two ruff versions in play disagree about
    # whether an inline argv triggers S603, and one strips the noqa the other needs.
    scaffold_command = ["task", "connector:new", "NAME=scratch-connector", f"DIRECTION={direction}"]
    scaffold = subprocess.run(  # noqa: S603
        scaffold_command,
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert scaffold.returncode == 0, f"scaffold failed:\n{scaffold.stdout}\n{scaffold.stderr}"

    subprocess.run(
        ["uv", "sync", "--all-packages", "--quiet"],  # noqa: S607
        cwd=clone,
        check=True,
        capture_output=True,
        env=env,
    )

    r = subprocess.run(
        ["task", "check"],  # noqa: S607
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert r.returncode == 0, f"task check failed with a scaffolded package registered:\n{r.stdout}\n{r.stderr}"
