"""Gate 8: Docs <-> Reality Consistency.

The scaffold's docs are its spec, so every claim they make is checked against the repo. This is
the gate that found all eight defects fixed on 2026-07-31; each test below names the one it locks
down so a regression is self-explaining.

Usage: uv run pytest tests/scaffold/cat8_docs_consistency.py -v

Taskfile targets are read by parsing Taskfile.yml rather than by running `task --list-all`, so
this gate holds in CI, where go-task is not installed.
"""

import json
import re

import pytest
import yaml

from ._scaffold import ROOT, template_only

README = (ROOT / "README.md").read_text()
AGENTS = (ROOT / "AGENTS.md").read_text()
CLAUDE = (ROOT / "CLAUDE.md").read_text()
WORKFLOW = (ROOT / "WORKFLOW.md").read_text()
GITIGNORE = (ROOT / ".gitignore").read_text()
TASKFILE_TEXT = (ROOT / "Taskfile.yml").read_text()
DEFINED_TARGETS = set(yaml.safe_load(TASKFILE_TEXT)["tasks"])

# Command heads that need no prerequisites entry: shell builtins, coreutils, and the installers
# the prerequisites section itself uses to bootstrap the real tools.
SHELL_LEVEL = {
    "cd",
    "echo",
    "curl",
    "sh",
    "bash",
    "brew",
    "npm",
    "mkdir",
    "rm",
    "cp",
    "mv",
    "chmod",
    "ls",
    "cat",
    "python",
    "python3",
    "export",
    "source",
    "#",
    # Ships with uv, which the prerequisites section does document.
    "uvx",
}

# Shell grammar, not executables — these appear as the first token of a line inside loops and
# conditionals (`for f in ...; do` / `done`).
SHELL_KEYWORDS = {
    "for",
    "do",
    "done",
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "while",
    "until",
    "case",
    "esac",
    "in",
}


def fenced(text: str, lang: str) -> list[str]:
    return re.findall(rf"```{lang}\n(.*?)```", text, re.DOTALL)


def prerequisites() -> str:
    return README.split("## Prerequisites")[1].split("## Bootstrap Order")[0].lower()


# --- embedded snippets must be valid in their own syntax ---------------------------------------


@pytest.mark.parametrize("i", range(len(fenced(README, "yaml"))))
@template_only
def test_readme_yaml_snippets_parse(i: int) -> None:
    """Locks defect 1: the Taskfile snippet used `cmds: [... {{.X}} ...]`, where `{{` opens a
    flow mapping inside a flow sequence and YAML parsing fails."""
    yaml.safe_load(fenced(README, "yaml")[i])


@pytest.mark.parametrize("i", range(len(fenced(README, "json"))))
@template_only
def test_readme_json_snippets_parse(i: int) -> None:
    json.loads(fenced(README, "json")[i])


@template_only
def test_readme_taskfile_snippet_matches_the_real_taskfile() -> None:
    """The snippet is the real Taskfile parameterised on the package name, nothing else."""
    expected = TASKFILE_TEXT.replace("APP: pkg_pulse", "APP: <your_package_name>")
    assert fenced(README, "yaml")[0] == expected, "README Taskfile snippet has drifted from Taskfile.yml"


@pytest.mark.parametrize("name", ["dispatch_tasks.py", "collect_handoffs.py"])
@template_only
def test_readme_script_snippets_match_disk(name: str) -> None:
    """Locks defect 7."""
    order = ["dispatch_tasks.py", "collect_handoffs.py"]
    snippet = fenced(README, "python")[order.index(name)]
    assert snippet.strip() == (ROOT / "scripts" / name).read_text().strip(), (
        f"README snippet for {name} has drifted from scripts/{name}"
    )


# --- documented commands must exist and be invocable -------------------------------------------


def test_documented_task_targets_are_defined() -> None:
    referenced = set(re.findall(r"`task ([a-z][a-z0-9:_-]*)", README + AGENTS)) - {"-l"}
    assert referenced, "no `task <target>` references found — check the regex"
    assert not (referenced - DEFINED_TARGETS), (
        f"docs reference undefined targets: {sorted(referenced - DEFINED_TARGETS)}"
    )


@pytest.mark.parametrize("doc", ["README.md", "AGENTS.md", "WORKFLOW.md"])
def test_docs_use_go_task_var_syntax(doc: str) -> None:
    """Locks defects 2 and 3: `task dispatch --change X` exits 2 with `unknown flag: --change`."""
    text = (ROOT / doc).read_text()
    assert not re.search(r"task [a-z:_-]+ --change", text), (
        f"{doc} uses `task <target> --change`; go-task needs `task <target> CHANGE=<value>`"
    )


@pytest.mark.parametrize("name", ["dispatch_tasks.py", "collect_handoffs.py"])
def test_scripts_print_go_task_var_syntax(name: str) -> None:
    """Locks defect 3 at the source: the scripts print a next-step hint users copy verbatim."""
    text = (ROOT / "scripts" / name).read_text()
    assert not re.search(r"task [a-z:_-]+ --change", text), f"scripts/{name} prints a command go-task rejects"


@template_only
def test_quality_gate_table_commands_are_defined() -> None:
    table = README.split("## Quality Gates")[1].split("##")[0]
    targets = set(re.findall(r"`task ([a-z][a-z0-9:_-]*)`", table))
    assert targets, "the quality-gate table lists no commands"
    assert not (targets - DEFINED_TARGETS), (
        f"quality-gate table references undefined targets: {sorted(targets - DEFINED_TARGETS)}"
    )


# --- bootstrap contract ------------------------------------------------------------------------


@template_only
def test_openlore_init_is_documented_before_analyze() -> None:
    """Locks defect 4: `openlore analyze` fails with 'No openlore configuration found' without it.

    Scoped to the bootstrap step's own fenced block — `openlore analyze` is also named in the
    stack-responsibilities table near the top, which says nothing about ordering.
    """
    step = README.split("### 4. Initialize OpenLore")[1].split("### 5.")[0]
    block = fenced(step, "bash")[0]
    assert "openlore init" in block, "bootstrap step 4 must run `openlore init`"
    assert block.index("openlore init") < block.index("openlore analyze"), (
        "`openlore init` must come before `openlore analyze`"
    )


def test_bootstrap_script_runs_openlore_init_before_analyze() -> None:
    bootstrap = (ROOT / "bootstrap.sh").read_text()
    assert "openlore init" in bootstrap, "bootstrap.sh must run `openlore init`"
    assert bootstrap.index("openlore init") < bootstrap.index("openlore analyze")


@template_only
def test_install_hook_is_documented_as_forbidden() -> None:
    """Locks defect 8: `openlore drift --install-hook` overwrites the pre-commit framework shim."""
    assert "--install-hook" in README, "README must address `openlore drift --install-hook`"
    context = README[README.index("--install-hook") - 400 : README.index("--install-hook") + 400]
    assert "not" in context.lower(), (
        "`--install-hook` must be documented as something not to run — it takes ownership of "
        ".git/hooks/pre-commit away from the pre-commit framework"
    )


@template_only
def test_prerequisites_cover_every_tool_the_bootstrap_invokes() -> None:
    """Case-insensitive: the README documents 'Node.js 20.19+', not a bare `node`."""
    prereq = prerequisites()
    heads: set[str] = set()
    for block in fenced(README, "bash"):
        # Join backslash continuations first, or a flag on its own line reads as a command.
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for segment in re.split(r"&&|\|\||[|;]", line):
                tokens = segment.strip().split()
                if not tokens:
                    continue
                head = tokens[0]
                # Skip flags, paths, variable expansions, shell keywords, and agent slash
                # commands like `/opsx:propose` — none of them are executables to document.
                if head.startswith(("-", "/", '"', "'", "$")) or head in SHELL_KEYWORDS:
                    continue
                heads.add(head)
    undocumented = {h for h in heads - SHELL_LEVEL if h.lower() not in prereq}
    assert not undocumented, (
        f"bootstrap steps invoke {sorted(undocumented)} but the prerequisites section never mentions them"
    )


# --- referenced paths and ignore rules ---------------------------------------------------------


def test_agents_md_referenced_paths_exist() -> None:
    # HANDOFF.md is written per worktree session and gitignored at the repo root, so AGENTS.md
    # naming it is correct. cat1 asserts it stays ignored; requiring it here would be wrong.
    #
    # openspec/specs/ is the empty-directory class: git cannot carry it, so it is absent from a
    # fresh clone until bootstrap.sh runs `mkdir -p`. cat1 tests that contract instead.
    per_session = {"HANDOFF.md", "openspec/specs/", "openspec/changes/"}
    referenced = set(re.findall(r"`([a-zA-Z_][a-zA-Z0-9_./-]*\.(?:md|ya?ml|toml|json))`", AGENTS))
    referenced |= set(re.findall(r"`([a-zA-Z_][a-zA-Z0-9_./-]*/)`", AGENTS))
    referenced -= per_session
    missing = {r for r in referenced if "<" not in r and "*" not in r and not (ROOT / r.rstrip("/")).exists()}
    assert not missing, f"AGENTS.md references paths that do not exist: {sorted(missing)}"


@template_only
def test_readme_gitignore_snippet_matches_the_real_file() -> None:
    """Locks defect 5: the snippet ignored only the call-graph db, the real file ignores .openlore/."""
    snippet = README.split("Add these to `.gitignore`:")[1].split("```")[1]
    rules = [line for line in snippet.strip().splitlines() if line and not line.startswith("#")]
    assert rules, "gitignore snippet lists no rules"
    for rule in rules:
        assert rule in GITIGNORE, f"README documents ignore rule {rule!r} that .gitignore lacks"


def test_claude_md_states_phi_guardrails() -> None:
    """This is a healthcare data platform template; CLAUDE.md ships to every generated repo.

    The rules are restated in CLAUDE.md rather than inherited from a personal global config,
    because a generated repo has no access to that config.
    """
    assert re.search(r"^#+ .*PHI", CLAUDE, re.M | re.I), "CLAUDE.md needs a PHI section"
    lowered = CLAUDE.lower()
    for claim, phrase in (
        ("no PHI in logs/fixtures", "no phi in logs"),
        ("synthetic data only", "synthetic data only"),
        ("never send PHI externally", "never send phi"),
    ):
        assert phrase in lowered, f"CLAUDE.md PHI section must state: {claim}"


def test_claude_md_commands_are_defined_targets() -> None:
    referenced = set(re.findall(r"`task ([a-z][a-z0-9:_-]*)", CLAUDE)) - {"-l"}
    assert referenced, "CLAUDE.md documents no task commands"
    assert not (referenced - DEFINED_TARGETS), (
        f"CLAUDE.md references undefined targets: {sorted(referenced - DEFINED_TARGETS)}"
    )


def test_claude_md_uses_go_task_var_syntax() -> None:
    assert not re.search(r"task [a-z:_-]+ --change", CLAUDE), (
        "CLAUDE.md uses `task <target> --change`; go-task needs `CHANGE=<value>`"
    )


def test_contracts_forbid_side_cloning() -> None:
    """Cross-repo integration goes through a published surface, never a clone of the producer."""
    publishes = (ROOT / "docs/contracts/publishes.md").read_text().lower()
    consumes = (ROOT / "docs/contracts/consumes.md").read_text().lower()
    assert "never" in publishes and "clon" in publishes, (
        "publishes.md must state that integration never happens by cloning another repo"
    )
    assert "never" in consumes and "clon" in consumes, (
        "consumes.md must state that a dependency is never satisfied by cloning the producer"
    )


def test_consumes_md_registers_customerio_export() -> None:
    """5.1: the forward consent ingress's Snowflake read must be a named, pinned entry.

    Names both landing schemas and the pinned `CONTRACT_COLUMNS` set (task 2.1) so a column
    drop on either side of the contract is traceable to this entry, not just this task's diff.
    """
    consumes = (ROOT / "docs/contracts/consumes.md").read_text()
    assert "streamline.cio_raw" in consumes, "consumes.md must name the cio_raw landing schema"
    assert "streamline.cio_prod" in consumes, "consumes.md must name the cio_prod landing schema"
    assert "ADR-0005" in consumes, "consumes.md must cross-link ADR-0005 as the source of the export mechanism"
    contract_columns = ("subject_key", "channel", "to_state", "message_id", "event_time")
    for column in contract_columns:
        assert f"`{column}`" in consumes, f"consumes.md must name pinned column {column!r}"


def test_consumes_md_registers_twenty_metadata_api() -> None:
    """pulse-app-scaffold 3.5: the Metadata API the artifact serializes against is a named entry.

    The entry must name the committed artifact path and the version keys the artifact pins its
    shape with, and those values must equal the committed artifact's — a doc that pins a version
    the artifact no longer carries is the drift this gate exists to catch. The upstream image tag
    is named too, because that is what fixes the server-side shape at deploy time.
    """
    consumes = (ROOT / "docs/contracts/consumes.md").read_text()
    artifact_path = "packages/twenty-app/artifact/operations.json"
    assert artifact_path in consumes, f"consumes.md must name the artifact path {artifact_path!r}"
    artifact = json.loads((ROOT / artifact_path).read_text())
    for key in ("artifactVersion", "catalogVersion"):
        assert f"`{key}`" in consumes, f"consumes.md must name the pinned version key {key!r}"
        assert f"`{artifact[key]}`" in consumes, (
            f"consumes.md must pin {key} to the committed artifact's value {artifact[key]!r}"
        )
    assert "twentycrm/twenty" in consumes, (
        "consumes.md must name the pinned upstream image the Metadata API shape follows"
    )
    for issue in ("DNA-908", "DNA-909"):
        assert issue in consumes, f"consumes.md must cross-link {issue}"


def test_adr_log_is_append_only_and_seeded() -> None:
    adr_dir = ROOT / "docs/adr"
    numbered = sorted(p for p in adr_dir.glob("ADR-*.md") if not p.name.startswith("ADR-0000"))
    assert numbered, "docs/adr/ needs at least ADR-0001"
    assert "append-only" in (adr_dir / "ADR-0000-template.md").read_text().lower(), (
        "the ADR template must state that the log is append-only"
    )
    for adr in numbered:
        head = adr.read_text()[:400]
        assert re.search(r"\*\*Status\*\*:\s*(Proposed|Accepted|Superseded)", head), (
            f"{adr.name} needs a Status of Proposed, Accepted, or Superseded"
        )


def test_adr_numbers_are_unique() -> None:
    numbers = [m.group(1) for p in (ROOT / "docs/adr").glob("ADR-*.md") if (m := re.match(r"ADR-(\d{4})", p.name))]
    duplicates = {n for n in numbers if numbers.count(n) > 1}
    assert not duplicates, f"duplicate ADR numbers: {sorted(duplicates)}"


@pytest.mark.parametrize("artifact", [".planning/", "docs/ade-compare.md", "new-repo.sh"])
def test_bootstrap_strips_template_authoring_artifacts(artifact: str) -> None:
    """These exist to build the template and are meaningless — or actively wrong — downstream.

    pulse-check1 shipped with .planning/ notes whose prose the package rename had rewritten into
    nonsense, and with new-repo.sh, which no project needs.
    """
    bootstrap = (ROOT / "bootstrap.sh").read_text()
    removal = re.search(r"^rm -rf .*$", bootstrap, re.M | re.S)
    assert removal, "bootstrap.sh must remove template-authoring artifacts"
    assert artifact.rstrip("/") in bootstrap, f"bootstrap.sh must delete {artifact} from the generated repo"


@pytest.mark.parametrize("doc", ["README.md", "CLAUDE.md", "CONTRIBUTING.md"])
def test_bootstrap_replaces_identity_documents(doc: str) -> None:
    """These describe repo-ade, and the package rename cannot fix prose.

    A generated repo whose CLAUDE.md says "this is a GitHub template repository" misleads every
    agent that reads it. bootstrap.sh overwrites them with project stubs — the GitHub-template
    equivalent of copier's _skip_if_exists.
    """
    bootstrap = (ROOT / "bootstrap.sh").read_text()
    assert re.search(rf"^cat > {re.escape(doc)} <<", bootstrap, re.M), (
        f"bootstrap.sh must write a project stub over {doc}"
    )


def test_generated_claude_stub_keeps_phi_guardrails() -> None:
    """The stub is what a project actually reads; PHI rules must survive the replacement."""
    bootstrap = (ROOT / "bootstrap.sh").read_text()
    stub = bootstrap.split("cat > CLAUDE.md <<CLAUDE_STUB")[1].split("CLAUDE_STUB")[0].lower()
    for phrase in ("no phi in logs", "synthetic data only", "never send phi"):
        assert phrase in stub, f"the generated CLAUDE.md stub must state: {phrase}"


def test_bootstrap_stamps_the_template_version() -> None:
    """Without the stamp, `task template:diff` has no baseline — a template clone shares no
    history with the template, so nothing else records what the repo is level with."""
    bootstrap = (ROOT / "bootstrap.sh").read_text()
    assert ".ade-template-version" in bootstrap, "bootstrap.sh must record the template commit in .ade-template-version"


@template_only
def test_readme_states_retrofit_is_unsupported() -> None:
    """A GitHub template only makes new repos; copier's retrofit has no equivalent here."""
    assert re.search(r"retrofit", README, re.I), (
        "README must say whether an existing repo can adopt this template (it cannot)"
    )


def test_ci_lessons_entries_are_dated() -> None:
    """An undated lesson cannot be aged out or correlated with a regression."""
    lessons = (ROOT / "docs/ci-lessons.md").read_text()
    bullets = [line for line in lessons.splitlines() if line.startswith("- **")]
    assert bullets, "docs/ci-lessons.md has no entries"
    for bullet in bullets:
        assert re.match(r"- \*\*\d{4}-\d{2}-\d{2} — ", bullet), (
            f"ci-lessons entry must start with an ISO date: {bullet[:60]}"
        )


@template_only
def test_mcp_config_location_is_accurate() -> None:
    """Locks defect 6: the tree promised .claude/settings.json as the MCP config.

    `.claude/settings.json` now legitimately exists as the agent permission allowlist, so this
    checks that nothing describes it as the MCP config rather than banning the filename.
    """
    assert ".mcp.json" in README, "README must document .mcp.json"
    offenders = [
        line.strip() for line in README.splitlines() if "settings.json" in line and re.search(r"\bMCP\b", line)
    ]
    assert not offenders, f"README ties settings.json to MCP config; servers live in .mcp.json: {offenders}"


@template_only
def test_documented_mcp_server_matches_mcp_json() -> None:
    snippet = json.loads(fenced(README, "json")[0])
    actual = json.loads((ROOT / ".mcp.json").read_text())
    assert snippet["mcpServers"].keys() == actual["mcpServers"].keys()


@template_only
def test_target_tree_lists_every_committed_top_level_path() -> None:
    """A committed top-level entry absent from the tree is undocumented surface area."""
    tree = re.search(r"```\n(your-project/.*?)```", README, re.DOTALL)
    assert tree, "README has no target-tree diagram"
    documented = tree.group(1)
    expected = [
        ".github",
        ".claude",
        ".mcp.json",
        ".pre-commit-config.yaml",
        "AGENTS.md",
        "README.md",
        "Taskfile.yml",
        "docs",
        "openspec",
        "pyproject.toml",
        "scripts",
        "src",
        "templates",
        "tests",
        "uv.lock",
    ]
    missing = [p for p in expected if p not in documented]
    assert not missing, f"target tree omits committed paths: {missing}"


def test_workflow_targets_are_defined() -> None:
    """WORKFLOW.md is the operating guide a generated repo reads first; a stale target there
    sends someone down a command that does not exist."""
    referenced = set(re.findall(r"`task ([a-z][a-z0-9:_-]*)", WORKFLOW)) - {"-l"}
    assert referenced, "WORKFLOW.md documents no task commands"
    assert not (referenced - DEFINED_TARGETS), (
        f"WORKFLOW.md references undefined targets: {sorted(referenced - DEFINED_TARGETS)}"
    )


def test_workflow_does_not_recommend_install_hook() -> None:
    """`openlore drift --install-hook` overwrites the pre-commit framework's shim."""
    for line in WORKFLOW.splitlines():
        if "--install-hook" in line:
            assert re.search(r"\b(not|never|do not)\b", line, re.I), (
                f"WORKFLOW.md mentions --install-hook without warning against it: {line.strip()}"
            )
