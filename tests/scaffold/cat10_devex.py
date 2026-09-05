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
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from ._scaffold import ROOT, have

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
    """Fix 3: task verify declares CHANGE, and a documented target creates .openlore on a fresh clone."""
    assert "CHANGE" in TARGETS["verify"].get("requires", {}).get("vars", [])
    assert "lore:init" in TARGETS or "openlore init" in _cmds("install")


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


@open_finding
def test_connector_new_supports_inbound_direction():
    """Fix 7: the scaffold renders an inbound variant, not only outbound."""
    r = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/connector_new.py", "--help"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert "--direction" in r.stdout and "inbound" in r.stdout, r.stdout[-600:]


@open_finding
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
    """Time clone plus the documented install. Prints `TTHW_INSTALL_SECONDS=<n>` for the ledger."""
    clone = tmp_path / "pulse-fresh"
    t0 = time.monotonic()
    subprocess.run(["git", "clone", "-q", str(ROOT), str(clone)], check=True)  # noqa: S603, S607
    env = {**os.environ, "UV_NO_PROGRESS": "1"}
    r = subprocess.run(
        ["uv", "sync", "--all-packages"],  # noqa: S607
        cwd=clone,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = round(time.monotonic() - t0)
    print(f"TTHW_INSTALL_SECONDS={seconds}", file=sys.stderr)
    assert r.returncode == 0, r.stderr[-2000:]
