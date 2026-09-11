"""Gate 4 (CI half): the workflows only invoke commands that exist.

cat4_command_contract.sh checks the Taskfile from the developer's side and needs go-task
installed. This module checks the same contract from CI's side in pure Python, so it runs on
runners where go-task may not be present.

Usage: uv run pytest tests/scaffold/cat4_ci_contract.py -v

Why this exists: `.github/workflows/main.yml` ran `make check` against a repo with no Makefile.
Every run from the repo's first commit through 2026-07-31 failed with "No rule to make target
'check'", and nothing caught it — cat4's shell half validates Taskfile targets, but nothing read
the workflows. A scaffold whose CI is broken teaches every generated repo that red CI is normal.
"""

import re
from pathlib import Path

import pytest
import yaml

from ._scaffold import ROOT

WORKFLOW_DIR = ROOT / ".github/workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
TASKFILE = yaml.safe_load((ROOT / "Taskfile.yml").read_text())
DEFINED_TARGETS = set(TASKFILE["tasks"])

# Executables a GitHub runner provides, or that a step in these workflows installs.
KNOWN_TOOLS = {
    "task",  # installed by arduino/setup-task
    "uv",  # installed by ./.github/actions/setup-python-env
    "uvx",
    "python",
    "python3",
    "git",
    "echo",
    "bash",
    "sh",
    "cd",
    "mkdir",
    "cp",
    "mv",
    "rm",
    "ls",
    "cat",
    "curl",
    "sudo",  # Postgres provisioning step (main.yml quality job, critical-path-verification 1.2)
    "test",
    "true",
}

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

# Runners that were never provisioned. `make` is called out by name because it is the specific
# way this repo's CI broke, and because the docs designate go-task as the only task runner.
FORBIDDEN_RUNNERS = {"make", "just", "rake", "invoke"}


def run_steps(workflow: Path) -> list[tuple[str, str]]:
    """Every `run:` block in a workflow, as (job_name, script) pairs."""
    data = yaml.safe_load(workflow.read_text())
    out = []
    for job_name, job in (data.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and "run" in step:
                out.append((job_name, str(step["run"])))
    return out


def command_heads(script: str) -> list[str]:
    """First token of each command in a shell snippet.

    Joins backslash continuations so a flag on its own line is not mistaken for a command, and
    splits on &&, ||, | and ; so chained commands are all seen.
    """
    heads = []
    joined = re.sub(r"\\\n\s*", " ", script)
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for segment in re.split(r"&&|\|\||[|;]", line):
            tokens = segment.strip().split()
            if not tokens:
                continue
            head = tokens[0]
            if head.startswith(("-", "/", '"', "'", "$")) or head in SHELL_KEYWORDS:
                continue
            if "=" in head and not head.startswith("="):  # VAR=value prefix
                continue
            heads.append(head)
    return heads


def task_targets(script: str) -> list[str]:
    """Targets invoked as `task <target>`, ignoring flags and VAR=value arguments."""
    joined = re.sub(r"\\\n\s*", " ", script)
    return [m.group(1) for m in re.finditer(r"\btask\s+((?!-)[A-Za-z0-9:_-]+)", joined) if "=" not in m.group(1)]


def test_workflows_exist() -> None:
    assert WORKFLOWS, f"no workflow files found in {WORKFLOW_DIR}"


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_every_task_invocation_resolves(wf: Path) -> None:
    for job, script in run_steps(wf):
        for target in task_targets(script):
            assert target in DEFINED_TARGETS, (
                f"{wf.name} job '{job}' runs `task {target}`, which Taskfile.yml does not define"
            )


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_no_forbidden_task_runner(wf: Path) -> None:
    """The exact regression: `make check` in a repo whose only runner is go-task."""
    for job, script in run_steps(wf):
        for head in command_heads(script):
            assert head not in FORBIDDEN_RUNNERS, (
                f"{wf.name} job '{job}' invokes `{head}`, but this repo's task runner is go-task "
                f"and no {head} file exists"
            )


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_every_command_is_a_known_tool(wf: Path) -> None:
    for job, script in run_steps(wf):
        for head in command_heads(script):
            assert head in KNOWN_TOOLS, (
                f"{wf.name} job '{job}' invokes `{head}`, which no step installs and no runner "
                f"provides by default; add it to KNOWN_TOOLS if a step does install it"
            )


def action_uses(path: Path) -> list[tuple[str, str]]:
    """Every `uses:` value in a workflow or composite action, as (owner/repo, ref)."""
    found = []
    for m in re.finditer(r"uses:\s*([^\s#]+)", path.read_text()):
        ref = m.group(1)
        if ref.startswith("./"):  # local composite action, versioned with this repo
            continue
        name, _, version = ref.partition("@")
        found.append((name, version))
    return found


ACTION_FILES = WORKFLOWS + sorted((ROOT / ".github/actions").rglob("action.yml"))


@pytest.mark.parametrize("path", ACTION_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_third_party_actions_are_pinned_by_sha(path: Path) -> None:
    """A floating tag is mutable — the pinned code can change under you between runs.

    setup-uv also stopped publishing floating major tags at v8, so `@v9` does not resolve at all.
    Pin the 40-hex commit and keep the human-readable version in a trailing comment.
    """
    for name, version in action_uses(path):
        assert re.fullmatch(r"[0-9a-f]{40}", version), (
            f"{path.name} uses {name}@{version}; pin it to a 40-character commit SHA with the "
            f"version in a `# vX.Y.Z` comment"
        )


@pytest.mark.parametrize("path", ACTION_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_pinned_actions_record_their_version(path: Path) -> None:
    """A bare SHA is unreadable; the comment is what makes a bump reviewable."""
    for line in path.read_text().splitlines():
        if re.search(r"uses:\s*[^\s#]+@[0-9a-f]{40}", line):
            assert re.search(r"#\s*v?\d+\.\d+", line), (
                f"{path.name}: pinned action needs a trailing version comment: {line.strip()}"
            )


def test_ci_runs_the_check_target() -> None:
    """`check` is the contract between local and CI. CI must actually invoke it."""
    invoked = {t for wf in WORKFLOWS for _, s in run_steps(wf) for t in task_targets(s)}
    assert "check" in invoked, "no workflow runs `task check`; local and CI will drift the moment either changes"


def test_check_target_is_ci_safe() -> None:
    """openspec and openlore are npm globals runners do not install — they belong in `verify`."""
    resolved: list[str] = []
    queue = list(TASKFILE["tasks"]["check"].get("cmds", []))
    seen = set()
    while queue:
        cmd = queue.pop(0)
        if isinstance(cmd, dict) and "task" in cmd:  # `- task: lint`
            name = cmd["task"]
            if name in seen:
                continue
            seen.add(name)
            queue.extend(TASKFILE["tasks"][name].get("cmds", []))
        elif isinstance(cmd, str):
            resolved.append(cmd)
    joined = "\n".join(resolved)
    for tool in ("openspec", "openlore"):
        assert tool not in joined, (
            f"`task check` transitively runs `{tool}`, which CI does not install; keep it in `verify` instead"
        )
    assert resolved, "`task check` resolves to no commands"


PIN_PATH = ROOT / "packages/synthea-seed/src/synthea_seed/config/synthea-pin.yaml"


def scheduled_regen_profiles() -> list[tuple[str, str]]:
    """(workflow name, profile) for every `synthea:regen PROFILE=<p>` run on a schedule."""
    found = []
    for wf in WORKFLOWS:
        data = yaml.safe_load(wf.read_text())
        # `on:` parses as the boolean True in YAML 1.1 — check both spellings.
        triggers = data.get("on") or data.get(True) or {}
        if "schedule" not in triggers:
            continue
        for _, script in run_steps(wf):
            for match in re.finditer(r"\bsynthea:regen\b[^\n]*?\bPROFILE=([A-Za-z0-9_-]+)", script):
                found.append((wf.name, match.group(1)))
    return found


@pytest.mark.xfail(
    reason=(
        "staging has no committed manifest and cannot get one on ubuntu-latest: a 50k FHIR "
        "population measures ~221 GiB (500 patients = 2.21 GiB, run 34292720706 died at 41m34s "
        "with 'No space left on device'). Committing a manifest needs a population decision "
        "first — synthea-pin.yaml and pulse-runtime-readiness.md §2.1. Xpasses once one lands."
    ),
    strict=False,
)
def test_scheduled_regen_profiles_have_a_committed_manifest() -> None:
    """A verify-only scheduled job cannot pass until its bootstrap re-pin has actually run.

    Locks the 2026-09-08 lesson: synthea-regen.yml verified `staging` against a manifest that
    had never been authored, so all five scheduled runs since 2026-08-10 failed after paying for
    a 50k-patient generation. The change that shipped the workflow checked its task off on a
    smoke-parse; nothing asserted the input the schedule depends on exists.

    Marked xfail rather than deleted: the assertion is correct and the repo genuinely fails it.
    Removing it would restore the exact blind spot the lesson is about.
    """
    profiles = scheduled_regen_profiles()
    assert profiles, "no scheduled synthea:regen invocation found; this gate has lost its subject"
    pin = yaml.safe_load(PIN_PATH.read_text())
    for wf_name, profile_name in profiles:
        declared = pin["profiles"].get(profile_name)
        assert declared, f"{wf_name} regenerates profile {profile_name!r}, which {PIN_PATH.name} does not declare"
        manifest = ROOT / "packages/synthea-seed" / declared["manifest"]
        assert manifest.is_file(), (
            f"{wf_name} verifies profile {profile_name!r} on a schedule, but {declared['manifest']} is not "
            f"committed; every scheduled run fails until the bootstrap re-pin is dispatched with repin=true"
        )
