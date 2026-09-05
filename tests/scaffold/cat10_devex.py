"""Gate 10: DevEx audit findings, as a regression ratchet.

One test per finding from the DevEx audit (`.planning/reports/2026-09-02-devex-scorecard.md`,
"Top 10 fixes" and "Below the cut"). While a defect exists its test is `xfail(strict=True)`: the
gate stays green, and `scripts/devex/check.py` counts the xfails as `devex_open_findings`. Fixing
a defect flips the marker off in the same PR; from then on a regression fails `task check`.

The number this gate produces is a count of open findings, never a 0-10. The only 0-10 comes from
the LLM-judged audit in docs/process/devex-audit/README.md, whose specs this gate also freezes
(`test_audit_protocol_is_frozen`).

Usage: uv run pytest tests/scaffold/cat10_devex.py -v
       uv run pytest tests/scaffold/cat10_devex.py -m slow -v   # fresh-clone TTHW
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from ._scaffold import ROOT, git, have

TASKFILE_TEXT = (ROOT / "Taskfile.yml").read_text()
TASKFILE = yaml.safe_load(TASKFILE_TEXT)
TARGETS: dict = TASKFILE["tasks"]
MKDOCS = yaml.safe_load((ROOT / "mkdocs.yml").read_text())
README = (ROOT / "README.md").read_text()
CONTRIBUTING = (ROOT / "CONTRIBUTING.md").read_text()
DOCS = ROOT / "docs"
AUDIT_DIR = DOCS / "process/devex-audit"
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))

open_finding = pytest.mark.xfail(strict=True, reason="open DevEx audit finding")


def _cmds(target: str) -> str:
    return "\n".join(str(c) for c in TARGETS[target].get("cmds", []))


def _nav_pages(node) -> set[str]:
    if isinstance(node, str):
        return {node}
    if isinstance(node, list):
        return set().union(*(_nav_pages(n) for n in node)) if node else set()
    if isinstance(node, dict):
        return set().union(*(_nav_pages(v) for v in node.values())) if node else set()
    return set()


# --- Fix 10 (L): scaffold and authoring guide ------------------------------------------------


def test_connector_scaffold_command_exists():
    """`task connector:new NAME=x` exists and a template tree backs it."""
    assert "connector:new" in TARGETS
    assert (ROOT / "templates/connector").is_dir()


def test_connector_authoring_guide_exists_and_is_in_nav():
    guide = DOCS / "connectors/authoring.md"
    assert guide.is_file()
    assert "connectors/authoring.md" in _nav_pages(MKDOCS["nav"])


# --- Fix 2 (S): the kit's advertised surface resolves ----------------------------------------


def test_connector_kit_all_names_resolve():
    import pulse_core.connector as kit

    missing = [name for name in kit.__all__ if not hasattr(kit, name)]
    assert missing == [], f"__all__ promises names the package never imports: {missing}"


# --- Fix 8 (M): one canonical connector spec -------------------------------------------------


def test_connector_spec_has_one_canonical_copy():
    design = ROOT / "design/platform/pulse-standard-connector-spec.md"
    spec = ROOT / "openspec/specs/connectors/pulse-standard-connector-spec.md"
    if not (design.exists() and spec.exists()):
        return  # one copy remains: canonical by construction
    a, b = design.read_text().splitlines(), spec.read_text().splitlines()
    pointer = min(len(a), len(b)) <= 30  # the shorter file is a pointer, not a second spec
    assert a == b or pointer, f"two drifted copies: {len(a)} vs {len(b)} lines"


# --- Fix 7 (M): connector config errors name every variable at once --------------------------

_BILLING_VARS = (
    "BILLING_CONNECTOR_TOKEN",
    "BILLING_CONNECTOR_QUEUE_URL",
    "BILLING_CONNECTOR_LEDGER_BASE_URL",
)


def test_billing_config_reports_all_missing_variables_at_once(monkeypatch):
    from billing_connector.config import Config

    for var in (*_BILLING_VARS, "BILLING_CONNECTOR_STALE_AFTER"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(Exception) as excinfo:
        Config.from_env()
    text = str(excinfo.value)
    assert all(v in text for v in _BILLING_VARS), text


def test_billing_config_names_variable_on_invalid_value(monkeypatch):
    from billing_connector.config import Config

    for var, val in zip(_BILLING_VARS, ("x", "y", "http://ledger.invalid"), strict=True):
        monkeypatch.setenv(var, val)
    monkeypatch.setenv("BILLING_CONNECTOR_STALE_AFTER", "banana")
    with pytest.raises(Exception) as excinfo:
        Config.from_env()
    assert not isinstance(excinfo.value, ValueError) or "STALE_AFTER" in str(excinfo.value)
    assert "BILLING_CONNECTOR_STALE_AFTER" in str(excinfo.value)


# --- Fix 1 (S): the documented install installs the documented hooks -------------------------


def test_install_installs_pre_commit_hooks():
    assert "pre-commit install" in _cmds("install"), CONTRIBUTING


# --- Fix 4 (S): bootstrap.sh refuses to run in a generated repo ------------------------------


def test_bootstrap_refuses_generated_repo_and_points_at_task_install():
    r = subprocess.run(  # noqa: S603
        ["bash", str(ROOT / "bootstrap.sh")],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "task install" in out, out


# --- Fix 9 (M): the docs site is this repo's -------------------------------------------------


def test_docs_site_is_pulse_not_the_template():
    assert MKDOCS["site_name"].lower() != "repo-ade"
    assert "repo-ade" not in MKDOCS.get("repo_url", "")
    modules = (DOCS / "modules.md").read_text()
    assert "pkg_pulse.foo" not in modules


def test_mkdocstrings_documents_the_connector_kit():
    handlers = next(p for p in MKDOCS["plugins"] if isinstance(p, dict) and "mkdocstrings" in p)
    paths = handlers["mkdocstrings"]["handlers"]["python"]["paths"]
    assert any("pulse-core" in p for p in paths), paths


def test_every_docs_page_is_in_nav():
    pages = {str(p.relative_to(DOCS)) for p in DOCS.rglob("*.md")}
    off_nav = sorted(pages - _nav_pages(MKDOCS["nav"]))
    assert off_nav == [], off_nav


# --- Below the cut (S): shell gates run in an automated context ------------------------------


def test_test_all_runs_the_shell_gates():
    text = _cmds("test:all")
    for gate in ("cat2_toolchain.sh", "cat4_command_contract.sh", "cat7_gates_hooks.sh"):
        assert gate in text, f"task test:all does not run {gate}"


# --- Fix 6 (S): every action pin is a real SHA -----------------------------------------------

_USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.M)


def test_action_pins_are_real_shas():
    bad = []
    for wf in WORKFLOWS:
        for ref in _USES.findall(wf.read_text()):
            if ref.startswith("./") or "@" not in ref:
                continue
            sha = ref.rsplit("@", 1)[1]
            if not re.fullmatch(r"[0-9a-f]{40}", sha) or set(sha) == {"0"}:
                bad.append(f"{wf.name}: {ref}")
    assert bad == [], bad


# --- Fix 3 (S): CHANGE-taking targets declare it ---------------------------------------------

CHANGE_TARGETS = (
    "dispatch",
    "checkoff",
    "collect",
    "replan",
    "spec:validate",
    "spec:archive",
    "spec:status",
    "sync-docs",
    "linear:sync",
)


def test_change_taking_targets_require_change():
    missing = [t for t in CHANGE_TARGETS if "CHANGE" not in TARGETS[t].get("requires", {}).get("vars", [])]
    assert missing == [], missing


# --- Fix 5 (S) and Community items: prerequisites, owner, templates --------------------------


def test_readme_states_prerequisites():
    section = re.search(r"^##+\s*Prerequisites.*?(?=^##\s|\Z)", README, re.S | re.M | re.I)
    assert section, "README has no Prerequisites section"
    for tool in ("uv", "task", "Node", "Docker"):
        assert tool.lower() in section.group(0).lower(), tool


def test_repo_names_an_owner_and_a_place_to_ask():
    assert (ROOT / ".github/CODEOWNERS").is_file() or (ROOT / "CODEOWNERS").is_file()
    text = (README + CONTRIBUTING).lower()
    assert re.search(r"slack|#[a-z][a-z0-9-]+|owner|ask ", text), "no channel or owner named"


def test_issue_and_pr_templates_exist():
    assert (ROOT / ".github/ISSUE_TEMPLATE").is_dir()
    assert (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").is_file()


# --- Audit 2 (2026-09-04, scorecard ranked fixes): open findings for devex-eight-2 -----------

GUIDE = "docs/connectors/authoring.md"


def test_authoring_guide_linked_from_readme_and_contributing():
    """Fix 1: the best document in the repo is invisible from the two files GitHub shows first."""
    assert GUIDE in README and GUIDE in CONTRIBUTING


def test_docs_index_is_a_front_door():
    """Fix 2: docs/index.md is a real front door with a Getting started section, not a badge stub."""
    index = (DOCS / "index.md").read_text()
    assert re.search(r"^##+\s*Getting started", index, re.M | re.I), "no Getting started section"
    assert len(index.splitlines()) >= 40, "index.md is still a stub"
    assert "connectors/authoring.md" in index


def test_verify_requires_change_and_lore_init_exists():
    """devex-eight-2 fix 3: task verify declares CHANGE, and a documented target creates .openlore."""
    assert "CHANGE" in TARGETS["verify"].get("requires", {}).get("vars", [])
    assert "lore:init" in TARGETS or "openlore init" in _cmds("install")


def test_verify_guards_against_empty_change():
    """Audit 3 fix 2 (QA R1): `requires: vars: [CHANGE]` is satisfied by Taskfile.yml's empty CHANGE
    default, so `task verify` with no CHANGE runs the whole gate before failing. The target needs a
    precondition that fails when CHANGE is empty, before `check` runs."""
    verify = TARGETS["verify"]
    pre = " ".join(str(p.get("sh", p) if isinstance(p, dict) else p) for p in verify.get("preconditions", []))
    first_cmd = str(verify.get("cmds", [""])[0])
    guarded = ("CHANGE" in pre) or (
        "CHANGE" in first_cmd and ("exit" in first_cmd or "test -n" in first_cmd or "fail" in first_cmd)
    )
    assert guarded, "task verify has no fail-fast guard on an empty CHANGE"


@pytest.mark.slow
@pytest.mark.skipif(not have("task"), reason="go-task not installed")
def test_verify_without_change_fails_fast():
    """Behavioural twin of the guard test, slow because a missing guard runs the whole gate."""
    t0 = time.monotonic()
    r = subprocess.run(["task", "verify"], cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S607
    seconds = time.monotonic() - t0
    assert r.returncode != 0
    if "CHANGE" not in " ".join(str(p) for p in TARGETS["verify"].get("preconditions", [])):
        pytest.xfail(f"no guard yet; verify ran {seconds:.0f}s before failing")
    assert seconds < 15, f"task verify without CHANGE ran {seconds:.0f}s before failing"


def test_connector_new_warns_about_prior_art(tmp_path):
    """Fix 4: scaffolding a name that already exists under packages/ocean/services names the prior art."""
    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "scripts/connector_new.py",
            "--name",
            "pocar",
            "--root",
            str(tmp_path),
            "--print-registrations",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "packages/ocean/services" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-800:]


def test_connector_kit_exports_jitter():
    """Fix 5: the guide names Jitter as a kit primitive; the package root must export it."""
    import pulse_core.connector as kit

    assert "Jitter" in kit.__all__ and hasattr(kit, "Jitter")


def test_template_ships_the_tests_the_guide_diagrams():
    """Fix 6: every test file named in the guide's rendered-tree diagram exists in the template.

    Scoped to the ```text rendered-tree fence itself (step 3), not the whole guide: the guide also
    names pulse-core's own gate tests (`test_connector_exports.py`,
    `test_connector_credential_gate.py`) in prose elsewhere, and those are not part of what
    `templates/connector/` renders.
    """
    template_tests = ROOT / "templates/connector/tests"
    guide_text = (ROOT / GUIDE).read_text()
    tree_diagram = re.search(r"```text\n(.*?)\n```", guide_text, re.S)
    assert tree_diagram, "guide has no ```text rendered-tree fence to check against the template"
    diagrammed = set(re.findall(r"(test_[a-z_]+\.py|factories\.py|conftest\.py)", tree_diagram.group(1)))
    shipped = {p.name.removesuffix(".tmpl") for p in template_tests.glob("*.tmpl")} | {
        p.name for p in template_tests.glob("*.py")
    }
    missing = sorted(diagrammed - shipped)
    assert not missing, f"guide diagrams test files the template does not ship: {missing}"


def test_connector_new_supports_inbound_direction():
    """Fix 7: the scaffold renders an inbound variant, not only outbound."""
    # Built as a variable rather than inline: the two ruff versions in play (the venv's and the
    # one .pre-commit-config.yaml pins) disagree about whether an inline literal argv triggers
    # S603, and one of them then strips the noqa the other needs — same as cat9.
    command = [sys.executable, "scripts/connector_new.py", "--help"]
    r = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603
    assert "--direction" in r.stdout and "inbound" in r.stdout, r.stdout[-600:]
    # The overlay behind the flag, not just the flag: cat9's golden pins what it renders.
    overlay = ROOT / "templates/connector/direction/inbound"
    assert overlay.is_dir(), f"--direction inbound has no overlay at {overlay}"
    service = overlay / "src/{{NAME}}/service.py.tmpl"
    assert service.is_file(), f"the inbound overlay ships no service module at {service}"
    assert {"RowSource", "CursorStore"} <= set(re.findall(r"\w+", service.read_text()))


def test_kit_has_changelog_and_deprecation_policy():
    """Fix 8: the kit reaches every connector on the next uv sync; it needs a changelog and a deprecations section."""
    assert (ROOT / "packages/pulse-core/CHANGELOG.md").is_file()
    spec = (ROOT / "openspec/specs/connector-kit/spec.md").read_text()
    assert re.search(r"^##+\s*Deprecations", spec, re.M), "connector-kit spec has no Deprecations section"


def test_readme_and_contributing_claims_are_current():
    """Fix 9: the countable claims in README and CONTRIBUTING match the tree."""
    archived = len([p for p in (ROOT / "openspec/changes/archive").iterdir() if p.is_dir()])
    m = re.search(r"(\d+|Twenty-two|twenty-two|twenty)\s+archived", README)
    if m:
        words = {"twenty": 20, "twenty-two": 22}
        claimed = words.get(m.group(1).lower()) or int(m.group(1))
        assert claimed == archived, f"README claims {claimed} archived changes, tree has {archived}"
    hooks = (ROOT / ".pre-commit-config.yaml").read_text()
    if "mypy" in CONTRIBUTING.lower():
        assert "mypy" in hooks, "CONTRIBUTING claims a mypy pre-commit hook that is not configured"


def test_editor_and_runtime_pins_exist():
    """Fix 10: .nvmrc pins Node 22 to match CI; .editorconfig and .vscode/extensions.json exist."""
    assert (ROOT / ".nvmrc").is_file() and (ROOT / ".nvmrc").read_text().strip().startswith("22")
    assert (ROOT / ".editorconfig").is_file()
    assert (ROOT / ".vscode/extensions.json").is_file()


def test_pr_template_names_task_check():
    """Below the cut: the PR checklist names the CI contract, not three of its eight parts."""
    assert "task check" in (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text()


def test_task_descriptions_carry_no_change_ids():
    """Below the cut: task descriptions are for the newcomer's first screen, not ticket bookkeeping."""
    noisy = [
        n
        for n, t in TARGETS.items()
        if isinstance(t, dict) and re.search(r"devex-eight task|DNA-\d+", str(t.get("desc", "")))
    ]
    assert noisy == [], noisy


# --- Audit 3 (2026-09-05, scorecard ranked fixes): open findings for devex-eight-3 -----------

_GIT_HELPER_FILES = ("tests/scaffold/cat5_glue_logic.py", "tests/scaffold/cat9_golden_workflow.py")


def test_scaffold_git_helpers_are_hermetic_to_global_signing():
    """Fix 1: the sandbox git helpers pin commit.gpgsign=false so a global signing config cannot fail the gate."""
    for rel in _GIT_HELPER_FILES:
        text = (ROOT / rel).read_text()
        assert "commit.gpgsign=false" in text, f"{rel} does not pin commit.gpgsign=false"


@pytest.mark.slow
@pytest.mark.skipif(not have("git"), reason="git not installed")
def test_scaffold_gates_survive_a_global_gpgsign_true(tmp_path: Path):
    """Behavioural twin: a hostile global config (gpgsign on, signing programs that always fail)
    must not fail the fixture gates that commit through the sandboxed `_git` helpers."""
    hostile = tmp_path / "gitconfig-global"
    hostile.write_text(
        "[init]\n\tdefaultBranch = main\n"
        "[commit]\n\tgpgsign = true\n"
        '[gpg]\n\tformat = x509\n\tprogram = false\n[gpg "x509"]\n\tprogram = false\n'
    )
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(hostile)}
    node_ids = [
        "tests/scaffold/cat5_glue_logic.py::test_commits_with_a_handoff_are_fine",
        "tests/scaffold/cat5_glue_logic.py::test_explicit_commits_bypass_the_history_scan",
        "tests/scaffold/cat9_golden_workflow.py::test_template_sync_survives_the_package_rename",
    ]
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-o", "addopts=", *node_ids],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


def test_connector_new_registers_pyright_not_mypy():
    """Fix 3: the rendered package declares pyright strict; the registration diff must add a pyright line, not a TYPED_PATHS entry."""
    # --print-registrations only reads pyproject.toml/Taskfile.yml, never writes — ROOT is safe.
    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "scripts/connector_new.py",
            "--name",
            "zapchk",
            "--root",
            str(ROOT),
            "--print-registrations",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = r.stdout + r.stderr
    assert "pyright -p packages/zapchk" in out, out[-800:]
    assert "TYPED_PATHS" not in out or "packages/zapchk/src" not in out.split("TYPED_PATHS", 1)[1][:200]


def test_task_lint_is_read_only():
    """Fix 4: `task lint` is documented read-only; ruff must not run with fix=true under it."""
    import tomllib

    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    ruff_fix = cfg.get("tool", {}).get("ruff", {}).get("fix", False)
    assert (not ruff_fix) or "--no-fix" in _cmds("lint"), "task lint rewrites files"


@pytest.mark.skipif(not have("ruff"), reason="ruff not on PATH")
def test_connector_new_renders_clean_regardless_of_name(tmp_path):
    """Fix 4 (cont.): the rendered scaffold passes `ruff check --no-fix` whichever side of
    `pulse_core` the connector's name sorts on. Without `pulse-core` declared explicitly
    first-party (`pyproject.toml.tmpl`'s isort section), a name sorting before it (`papchk`) and
    one sorting after it (`zapchk`) render with opposite import orders, and only one is clean —
    the I001 the DevEx audit found. `--root`/`--template` point registration and rendering at a
    scratch copy so this never touches the real `packages/` tree.
    """
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    (tmp_path / "Taskfile.yml").write_text((ROOT / "Taskfile.yml").read_text())
    for name in ("papchk", "zapchk"):
        render = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "scripts/connector_new.py",
                "--name",
                name,
                "--direction",
                "inbound",
                "--template",
                "templates/connector",
                "--dest",
                str(tmp_path / "packages" / name),
                "--root",
                str(tmp_path),
                "--apply-registrations",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert render.returncode == 0, render.stdout + render.stderr
        lint = subprocess.run(  # noqa: S603
            [shutil.which("ruff") or "ruff", "check", "--no-fix", f"packages/{name}"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert lint.returncode == 0, f"{name}: {lint.stdout}{lint.stderr}"


def test_scaffold_ships_a_working_declare_example():
    """Fix 5: the scaffold's handle_page declares through the kit instead of counting rows."""
    hits = list((ROOT / "templates/connector").rglob("service.py.tmpl"))
    assert hits, "no service template"
    # A real call on a code line, not the comment or docstring that tells the author to add one.
    call = re.compile(r"^\s*(?!#)[^\n`]*\bsubmit_with_retry\(", re.M)
    assert any(call.search(h.read_text()) for h in hits), (
        "no template calls submit_with_retry; handle_page is still a counting stub"
    )


def test_cursor_store_transport_errors_name_the_endpoint():
    """Fix 6: LedgerCursorStore wraps transport failures with the base URL tried and the variable that supplied it."""
    src = (ROOT / "packages/pulse-core/src/pulse_core/connector/rows.py").read_text()
    assert "httpx.TransportError" in src or "TransportError" in src, "cursor store does not catch transport errors"
    assert "base_url" in src and ("CursorStoreError" in src or "LedgerCursorStoreError" in src)


def test_authoring_guide_documents_every_exported_name():
    """Fix 7: the guide's import section names every `__all__` export, checked by a test that diffs them."""
    import pulse_core.connector as kit

    guide = (ROOT / GUIDE).read_text()
    missing = sorted(n for n in kit.__all__ if f"`{n}`" not in guide)
    assert missing == [], f"guide omits kit exports: {missing}"


def test_rendered_readme_next_steps_do_not_redo_registration():
    """Fix 8: the rendered README's Next steps must not tell the author to register a package the scaffold already registered."""
    readme = (ROOT / "templates/connector/README.md.tmpl").read_text()
    assert "already registered" in readme.lower() or "registered for you" in readme.lower(), (
        "rendered README still asks the author to register the package"
    )


def test_check_timings_are_recorded():
    """Fix 9: `task check` appends per-target timings to the ledger so gate regressions are visible."""
    assert "devex/timing" in _cmds("check") or "timing" in _cmds("check"), "task check records no timings"


def test_codeowners_names_the_connector_kit_owner_and_defect_template_exists():
    """Fix 10: a per-area CODEOWNERS line for the kit and a connector-kit-defect issue template."""
    co = (ROOT / ".github/CODEOWNERS").read_text()
    assert "pulse_core/connector" in co, "no per-area CODEOWNERS line for the kit"
    assert (ROOT / ".github/ISSUE_TEMPLATE/connector-kit-defect.yml").is_file()


# --- Measurement machinery: these pass from wave 0 and must stay green -----------------------


def test_devex_targets_exist():
    assert "devex:check" in TARGETS
    assert "devex:audit" in TARGETS


def test_ledger_exists_with_a_baseline_row():
    ledger = ROOT / ".planning/devex/loop.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert rows, "ledger is empty"
    assert rows[0]["kind"] == "audit" and "overall" in rows[0] and "connector" in rows[0]


def test_pytest_collects_two_digit_gate_files():
    """`cat[0-9]_*.py` silently skips cat10; the pattern must match this file's own name."""
    import fnmatch

    import tomllib

    patterns = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]["python_files"]
    assert any(fnmatch.fnmatch(Path(__file__).name, p) for p in patterns), patterns


def test_audit_protocol_is_frozen():
    """The rubric and agent specs match CHECKSUMS; a change to them is its own PR."""
    lines = (AUDIT_DIR / "CHECKSUMS").read_text().splitlines()
    recorded = dict(reversed(line.split()) for line in lines if line.strip())
    assert set(recorded) == {"README.md", "rubric.md", "task-a.md", "task-b.md", "task-c.md"}
    for name, digest in recorded.items():
        actual = hashlib.sha256((AUDIT_DIR / name).read_bytes()).hexdigest()
        assert actual == digest, f"{name} changed without regenerating CHECKSUMS"


def test_command_routes_to_runbook():
    text = (ROOT / ".claude/commands/devex-audit.md").read_text()
    assert "docs/process/devex-audit/README.md" in text


# --- TTHW: fresh clone to a synced environment (slow) ----------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not have("uv"), reason="uv not installed")
def test_tthw_fresh_clone_to_synced_env(tmp_path):
    """Time clone plus the documented install, warm cache and cold cache.

    Prints `TTHW_INSTALL_SECONDS_WARM=<n>` (ambient uv cache — what a repeat contributor sees) and
    `TTHW_INSTALL_SECONDS_COLD=<n>` (`UV_CACHE_DIR` pointed at an empty dir — the number a brand
    new machine actually sees) for the ledger. Audit 3's timings were only valid measured idle
    (devex-loop-lessons); this test already runs alone, so both arms stay comparable.
    """

    def _install(label: str, cache_dir: Path | None) -> tuple[int, int, str]:
        clone = tmp_path / f"pulse-fresh-{label}"
        t0 = time.monotonic()
        subprocess.run(["git", "clone", "-q", str(ROOT), str(clone)], check=True)  # noqa: S603, S607
        env = {**os.environ, "UV_NO_PROGRESS": "1"}
        if cache_dir is not None:
            env["UV_CACHE_DIR"] = str(cache_dir)
        r = subprocess.run(
            ["uv", "sync", "--all-packages"],  # noqa: S607
            cwd=clone,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return r.returncode, round(time.monotonic() - t0), r.stderr

    rc_warm, seconds_warm, err_warm = _install("warm", None)
    print(f"TTHW_INSTALL_SECONDS_WARM={seconds_warm}", file=sys.stderr)
    assert rc_warm == 0, err_warm[-2000:]

    cold_cache_dir = tmp_path / "uv-cache-cold"
    cold_cache_dir.mkdir()
    rc_cold, seconds_cold, err_cold = _install("cold", cold_cache_dir)
    print(f"TTHW_INSTALL_SECONDS_COLD={seconds_cold}", file=sys.stderr)
    assert rc_cold == 0, err_cold[-2000:]


# --- Audit 4 (2026-09-05b, scorecard ranked fixes): open findings for devex-eight-4 ----------
#
# Audit 4 at `5177d05` scored overall 6.0 and connector 5.6, down from 6.5/6.7, because PR #403
# shipped two defects onto the golden path while this gate read `devex_open_findings=0`
# throughout: no finding test rendered a connector and ran the real gate. Every test below
# asserts the behaviour its fix produces, run against a rendered tree or the repo's own output —
# never the presence of a config line (devex-loop lesson: #380's structural test closed a finding
# that was still open).

CONNECTOR_TEMPLATE = ROOT / "templates/connector"


def _render(dest_root: Path, name: str, direction: str) -> Path:
    """Render one connector into `dest_root/packages/<name>` and return the package directory.

    `--root` points registration and rendering at the scratch tree, so nothing here can reach the
    real `packages/` directory. Returns the package dir; raises with the script's own output when
    the scaffold itself fails, which is the failure mode worth reading.
    """
    dest = dest_root / "packages" / name
    command = [
        sys.executable,
        "scripts/connector_new.py",
        "--name",
        name,
        "--direction",
        direction,
        "--template",
        str(CONNECTOR_TEMPLATE),
        "--dest",
        str(dest),
        "--root",
        str(dest_root),
    ]
    r = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603
    assert r.returncode == 0, r.stdout + r.stderr
    return dest


@open_finding
def test_rendered_connector_suites_run_under_the_repos_import_mode(tmp_path: Path):
    """Fix 1: `task connector:new` renders a suite that `task test` can actually run.

    The repo runs `pytest --import-mode=importlib` over every package's tests in one process
    (`Taskfile.yml`'s TESTED_PATHS). Under that mode sys.path is not extended with the test file's
    directory, so the rendered `from factories import ...` raises ModuleNotFoundError — the
    defect PR #403 shipped, on both directions, name-independently.

    The run below includes `packages/billing-connector/tests` deliberately. That suite is the
    repo's one existing `tests` package, and it is what a new connector joins in TESTED_PATHS; a
    fix that gives the rendered tree its own top-level `tests` package collides with it inside
    pytest's plugin manager ("Plugin already registered under a different name"), so a fix
    verified on a rendered package alone is not verified at all.
    """
    packages = [_render(tmp_path, "aaachk", "outbound"), _render(tmp_path, "zzzchk", "inbound")]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(str(p / "src") for p in packages),
    }
    r = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "packages/billing-connector/tests",
            *[str(p / "tests") for p in packages],
            "--import-mode=importlib",
            "-o",
            "addopts=",
            "-q",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]


@open_finding
def test_rendered_connector_is_a_ruff_format_fixed_point(tmp_path: Path):
    """Fix 2: every file the scaffold renders is already formatted the way `task lint` wants.

    The outbound `def run(` signature joins to 118 characters against `line-length = 120`, which
    ruff's formatter then splits back out: an unconditional `task lint` failure on the default
    direction, in a file the author never touched. Checked over the whole rendered tree in both
    directions rather than that one signature, so the next long line is caught too.
    """
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    packages = [_render(tmp_path, "aaachk", "outbound"), _render(tmp_path, "zzzchk", "inbound")]
    ruff = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    r = subprocess.run(  # noqa: S603
        [ruff, "format", "--check", *[str(p) for p in packages]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr


@open_finding
def test_documented_install_leaves_the_clone_able_to_commit_python(tmp_path: Path):
    """Fix 3: after the documented install, the `openlore-drift` pre-commit hook has what it needs.

    `.openlore/` is gitignored, so it is absent from a fresh clone and the hook fails every commit
    that touches Python — the newcomer's third command, after two successes. `task lore:init` is
    idempotent and already safe on a fresh clone; the install must run it.

    Hermetic and credential-free: the chain is read from the Taskfile, and where `openlore` is on
    PATH the initialising step is then run for real in a scratch directory (`openlore init` needs
    no key — only `openlore generate` does) and its output directory asserted. No network, no
    global config touched.
    """
    install = _cmds("install")
    initialises = "lore:init" in install or "openlore init" in install
    assert initialises, "`task install` never initialises .openlore, so the first Python commit fails"
    if not have("openlore"):
        return
    r = subprocess.run(  # noqa: S603
        [shutil.which("openlore") or "openlore", "init", "--force"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / ".openlore").is_dir(), "openlore init produced no .openlore/ to satisfy the hook"


@open_finding
def test_readme_names_the_owner_and_the_channel_above_the_fold():
    """Fix 4: a reader who opens README.md learns who owns this and where to ask, without a hop.

    The rubric's internal-repo interpretation checks `README.md` specifically. Today
    `grep -in "slack|owner|channel" README.md` returns nothing at all; the information exists in
    `CONTRIBUTING.md` and can be lifted verbatim. "Above the fold" is the first 40 lines — one
    screenful, before the narrative starts.
    """
    fold = "\n".join(README.splitlines()[:40])
    owner = re.search(r"@[\w.-]+|CODEOWNERS|\bowner\b|\bmaintainer\b", fold, re.I)
    channel = re.search(r"#[a-z][a-z0-9-]{2,}|slack|linear|notion", fold, re.I)
    assert owner, "README's first 40 lines name no owner"
    assert channel, "README's first 40 lines name no place to ask"


@open_finding
def test_the_gate_measures_the_golden_path_not_the_command_listing():
    """Fix 5: `devex_open_findings` is a claim about the connector path, not about a task target.

    `test_connector_scaffold_command_exists` asserted that `task connector:new` is defined and a
    template directory backs it. Both held at `5177d05` while the command it names rendered a
    package that failed the repo's own gate in both directions, and this gate still read zero.
    The claim is replaced by the slow control below, which renders and gates; this test is the
    non-slow twin that keeps the replacement from being quietly dropped.
    """
    source = Path(__file__).read_text()
    assert "def test_connector_scaffold_command_exists(" not in source, (
        "the command-listing claim is still the gate's connector coverage"
    )
    assert "def test_rendered_connectors_pass_the_real_gate(" in source, "no render-and-gate control in this gate"


@pytest.mark.slow
@open_finding
def test_rendered_connectors_pass_the_real_gate(tmp_path: Path):
    """Fix 5, the control: render both directions, register them, run the repo's own gate.

    The gate here is `task check`'s lint, format and test constituents run over the rendered tree,
    not `task check` itself: this test runs inside `task test:all`, and `task check` would recurse
    into itself. Typecheck is left out because `pyright` is an npm global CI runners do not have
    (`docs/contracts/consumes.md`); the two defects this control exists to catch are a lint
    failure and a collection error.

    Marked `slow`, so it is deselected from the default run and does not enter the open-finding
    count — the non-slow twin above carries that. When fixes 1 and 2 land, this marker comes off
    with the second of them (tasks.md task 1.2), before wave 2 touches the twin.
    """
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    (tmp_path / "Taskfile.yml").write_text(TASKFILE_TEXT)
    packages = []
    for name, direction in (("aaachk", "outbound"), ("zzzchk", "inbound")):
        packages.append(_render(tmp_path, name, direction))
        register = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "scripts/connector_new.py",
                "--name",
                name,
                "--direction",
                direction,
                "--template",
                str(CONNECTOR_TEMPLATE),
                "--dest",
                str(tmp_path / "packages" / name),
                "--root",
                str(tmp_path),
                "--apply-registrations",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert register.returncode == 0, register.stdout + register.stderr
    ruff = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    for args in (["format", "--check"], ["check", "--no-fix"]):
        r = subprocess.run(  # noqa: S603
            [ruff, *args, *[str(p) for p in packages]],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 0, f"ruff {args[0]}: {r.stdout}{r.stderr}"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p / "src") for p in packages)}
    tests = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "packages/billing-connector/tests",
            *[str(p / "tests") for p in packages],
            "--import-mode=importlib",
            "-o",
            "addopts=",
            "-q",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tests.returncode == 0, (tests.stdout + tests.stderr)[-3000:]


@open_finding
def test_week_one_failures_name_the_repos_own_target(tmp_path: Path):
    """Fix 6: a failing gate names the `task` target that fixes it, not the underlying tool's.

    `task lint` prints ruff's diff and never mentions `task fmt`, which applies exactly it; a
    missing `openspec`/`openlore` prints the shell's `not found in $PATH` while the install line
    sits in `README.md`. Both are inherited messages the repo did not wrap, and both land in
    week one.

    The lint probe is behavioural and hermetic: `LINT_PATHS` is overridden to a scratch directory
    holding one deliberately unformatted file, so the real target runs against nothing in the
    tree. Where `task` is absent (CI installs uv and Python only), the lint half falls back to
    reading the target, which is why this test never skips.
    """
    broken = tmp_path / "broken.py"
    broken.write_text("def f( x ):\n  return x\n")
    if have("task"):
        r = subprocess.run(  # noqa: S603
            [shutil.which("task") or "task", "lint", f"LINT_PATHS={tmp_path}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode != 0, "the probe file did not fail lint; the probe is broken, not the message"
        assert "task fmt" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-1500:]
    else:
        assert "task fmt" in _cmds("lint"), "task lint's failure names no repo target"
    for target in ("spec:validate", "lore:drift"):
        text = _cmds(target) + str(TARGETS[target].get("preconditions", ""))
        assert "npm install -g" in text, f"{target} does not name the install line for its missing npm global"


@open_finding
def test_a_green_gate_leaves_the_tree_clean_and_summarises_itself():
    """Fix 7: the timing instrument is feedback, not an uncommitted diff the newcomer did not author.

    `scripts/devex/timing.py` appends a row per gate target to `.planning/devex/loop.jsonl`, a
    tracked file, so the first documented `task check` on a fresh clone ends with a dirty tree and
    no explanation anywhere in README, CONTRIBUTING or the guide. The path is read out of the
    script rather than restated here: whichever file the timing wrapper appends to must not be
    tracked. The ledger's `audit` rows are a different matter — they are the tracked receipt
    `test_ledger_exists_with_a_baseline_row` reads, and a fresh clone still needs them.

    The rows are worth keeping either way: printed back as the gate's closing summary they replace
    a red vendor warning with the one thing the newcomer wants to see.
    """
    timing = (ROOT / "scripts/devex/timing.py").read_text()
    written = re.search(r'LEDGER\s*=\s*ROOT\s*/\s*"([^"]+)"', timing)
    assert written, "cannot tell which file scripts/devex/timing.py appends to"
    tracked = git("ls-files", "--error-unmatch", written.group(1)).returncode == 0
    assert not tracked, f"a green `task check` dirties the tree: {written.group(1)} is tracked and appended to"
    last = str(TARGETS["check"]["cmds"][-1])
    assert "summary" in last, f"`task check` ends on a gate, not a per-target summary: {last}"


@open_finding
def test_guide_import_block_carries_the_errors_the_pipeline_raises():
    """Fix 8: an author who pastes the guide's import block gets the exceptions thrown at them.

    The block lists constructors and protocols and no error types, while `submit_with_retry`
    raises `TransientExhaustedError` and `LedgerCursorStore` raises `LedgerCursorStoreError`.
    Both are named in the guide's prose, which is why the every-export test passes; the paste
    block is what an author actually runs.
    """
    guide = (ROOT / GUIDE).read_text()
    block = re.search(r"^from pulse_core\.connector import \(\n(.*?)^\)$", guide, re.S | re.M)
    assert block, "the guide has no `from pulse_core.connector import (...)` block to paste"
    names = set(re.findall(r"^\s{4}([A-Za-z_]\w*),", block.group(1), re.M))
    import pulse_core.connector as kit

    unimportable = sorted(n for n in names if not hasattr(kit, n))
    assert unimportable == [], f"the paste block names what the kit does not export: {unimportable}"
    missing = sorted({"TransientExhaustedError", "LedgerCursorStoreError"} - names)
    assert missing == [], f"the paste block omits the errors the retry pipeline raises: {missing}"


@open_finding
def test_env_example_carries_the_variables_the_tooling_demands():
    """Fix 9: `Config.from_env` names the variables; `.env.example` names the file they go in.

    The variable names are read out of the scaffold's own config template rather than restated
    here, so the two cannot drift: whatever `{{UPPER}}_*` shape the template generates must have
    a commented example in `.env.example`. `PULSE_TWENTY_DEV_URL` and `PULSE_TWENTY_DEV_TOKEN`
    are the pair `task twenty:deploy TARGET=dev` demands by name and the file has never carried.
    """
    env_example = (ROOT / ".env.example").read_text()
    config_tmpl = (CONNECTOR_TEMPLATE / "src/{{NAME}}/config.py.tmpl").read_text()
    suffixes = sorted(set(re.findall(r'"\{\{UPPER\}\}(_[A-Z_]+)"', config_tmpl)))
    assert suffixes, "the config template no longer builds its variable names from {{UPPER}}"
    missing = [s for s in suffixes if s not in env_example]
    assert missing == [], f".env.example carries no connector block: {missing} unexampled"
    for var in ("PULSE_TWENTY_DEV_URL", "PULSE_TWENTY_DEV_TOKEN"):
        assert var in env_example, f".env.example does not name {var}"


@open_finding
def test_tthw_measures_clone_to_a_green_gate_in_both_arms():
    """Fix 10: the onboarding number covers the wall clock a newcomer actually waits.

    `test_tthw_fresh_clone_to_synced_env` times clone plus `uv sync` — 5s of the 152s a newcomer
    spends, because `task check` is 97 percent of it. A metric that omits the dominant term
    cannot detect the regression it exists for. Both cache arms must reach a green gate and
    report a total, not an install time.
    """
    source = Path(__file__).read_text()
    tthw = re.search(r"def test_tthw_[\w]*\(.*?(?=\n@|\ndef |\Z)", source, re.S)
    assert tthw, "no TTHW test in this gate"
    body = tthw.group(0)
    assert re.search(r'"task",\s*"check"|task check', body), "the TTHW test never reaches a green gate"
    for arm in ("TTHW_TOTAL_SECONDS_WARM", "TTHW_TOTAL_SECONDS_COLD"):
        assert arm in body, f"the TTHW test reports no {arm}"
