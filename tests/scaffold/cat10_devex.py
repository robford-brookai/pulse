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


@open_finding
def test_connector_scaffold_command_exists():
    """`task connector:new NAME=x` exists and a template tree backs it."""
    assert "connector:new" in TARGETS
    assert (ROOT / "templates/connector").is_dir()


@open_finding
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


@open_finding
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


@open_finding
def test_billing_config_reports_all_missing_variables_at_once(monkeypatch):
    from billing_connector.config import Config

    for var in (*_BILLING_VARS, "BILLING_CONNECTOR_STALE_AFTER"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(Exception) as excinfo:
        Config.from_env()
    text = str(excinfo.value)
    assert all(v in text for v in _BILLING_VARS), text


@open_finding
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


@open_finding
def test_docs_site_is_pulse_not_the_template():
    assert MKDOCS["site_name"].lower() != "repo-ade"
    assert "repo-ade" not in MKDOCS.get("repo_url", "")
    modules = (DOCS / "modules.md").read_text()
    assert "pkg_pulse.foo" not in modules


@open_finding
def test_mkdocstrings_documents_the_connector_kit():
    handlers = next(p for p in MKDOCS["plugins"] if isinstance(p, dict) and "mkdocstrings" in p)
    paths = handlers["mkdocstrings"]["handlers"]["python"]["paths"]
    assert any("pulse-core" in p for p in paths), paths


@open_finding
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
