# Repo ADE

## repository agent development environment scaffold

A composable development environment for agent-driven Python projects. Four open-source tools work together with thin glue scripts — no orchestration framework required.

## Purpose

This repo is the base template for projects developed with [Orca ADE](https://github.com/stablyai/orca) (parallel agents in isolated git worktrees). It wires together spec-driven planning, drift detection, and a post-session handoff protocol so that agents stay aligned with the design docs as the codebase evolves.

The design principle is **thin glue**: each tool owns its layer, and a handful of scripts + an AGENTS.md contract connect them. No competing orchestration runtime.

## Stack Responsibilities

| Component | Repo / Tool | Owns | Does Not Do |
|---|---|---|---|
| **Python Baseline** | [cookiecutter-uv](https://github.com/fpgmaas/cookiecutter-uv) | uv, ruff, mypy, pre-commit, pytest, GitHub Actions, MkDocs | Task running (we add Taskfile) |
| **Spec & Planning** | [OpenSpec](https://github.com/Fission-AI/OpenSpec) | Change lifecycle (proposal → design → specs → tasks → archive), `openspec validate`, Given/When/Then scenarios | Task dispatch, quality gates |
| **Drift & Memory** | [OpenLore](https://github.com/clay-good/OpenLore) | Call graph, `openlore analyze`, `openlore drift` (pre-commit), `orient()` MCP tool, architectural decision gates | Spec lifecycle, worktree management |
| **Execution** | [Orca ADE](https://github.com/stablyai/orca) | Git worktree isolation, parallel agent execution, diff review/merge, Orca CLI | Spec management, drift detection, quality gates |
| **Thin Glue** | This repo | Taskfile targets, `dispatch_tasks.py`, `collect_handoffs.py`, AGENTS.md contract, HANDOFF.md protocol | Does not replace any of the above |

## Agent Operating Contract

**These rules are binding for all AI agents working in this repo.** The AGENTS.md file (created during bootstrap) encodes them for agents running inside Orca worktrees.

### Hard Rules

1. **Tests are mandatory.** Every work-order must produce at least one test. An implementation that lands without a test is incomplete. Follow red-green-refactor: write the failing test first, watch it fail, implement, watch it pass.

2. **Implementation agents do not edit specs.** Agents working in Orca worktrees must NOT directly modify `openspec/specs/` or `openspec/changes/*/specs/`. If an agent discovers that a spec needs updating, it writes the proposed change to `HANDOFF.md` in the worktree root and stops.

3. **HANDOFF.md is the only bridge.** At session end, every Orca worktree agent writes a `HANDOFF.md` file at the worktree root. This file contains only spec-relevant updates — not implementation details, not style choices, not non-plan-changing decisions. The doc-updater agent reads these and applies changes via OpenSpec.

4. **Validation is a gate, not a suggestion.** `openspec validate` must pass before archive. `openlore drift` must pass before commit. `uv run pytest` must pass before merge. Do not skip these.

5. **Stop on design drift.** If the work reveals that the design doc or spec is wrong, stop. Do not improvise. Write the discrepancy to `HANDOFF.md` under a `## Design Drift` heading and flag it for human review.

6. **One task, one commit.** Each work-order should produce one atomic commit for rollback-friendly granularity.

7. **Use `orient()` before reading files.** If OpenLore MCP is available, call `orient("<task description>")` first. It returns relevant functions, call paths, insertion points, and matching spec sections — typically reducing orientation cost from ~30k tokens to ~1k.

## Prerequisites

Install these on your machine before bootstrapping:

```bash
# Python + uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node.js 20.19+ (for OpenSpec)
# Install via nvm, fnm, or your package manager

# OpenSpec CLI
npm install -g @fission-ai/openspec@latest

# OpenLore
npm install -g openlore

# go-task (Taskfile runner)
# macOS:
brew install go-task
# Linux: https://taskfile.dev/installation/

# Orca ADE
# Download from https://onorca.dev/download
# Or: brew install --cask stablyai/orca/orca

# git (bootstrap step 1 runs `git init`; usually already present)
git --version

# Optional: GitHub CLI (for PR/issue integration)
brew install gh
```

## Bootstrap Order

Run these steps in sequence. Do not skip ahead — each step depends on the previous.

### 1. Generate repo from cookiecutter-uv

```bash
uvx cookiecutter https://github.com/fpgmaas/cookiecutter-uv.git
# Follow prompts: project name, package name, description, etc.
cd <your-project-name>
git init && git add . && git commit -m "Initial scaffold from cookiecutter-uv"
```

### 2. Add Taskfile.yml

Create `Taskfile.yml` in the repo root. This replaces the Makefile/justfile that cookiecutter-uv may generate and adds the thin-glue targets:

```yaml
version: "3"

# Tasks are grouped by functional area, areas ordered by when you reach them, and alphanumeric
# within each area. `task -l` sorts alphabetically and would scatter that grouping, so the
# default task lists with --sort none to preserve it.
#
# Two lifecycles share this file, because a generated repo inherits it verbatim:
#   - area 1 runs in the TEMPLATE only, and is where a project begins;
#   - areas 2-9 run in whichever repo you are sitting in;
#   - area 10 runs in a GENERATED repo, periodically, to pull template fixes back down.

vars:
  APP: <your_package_name>
  SRC: src
  TESTS: tests
  CHANGE: ""
  VISIBILITY: --private

tasks:
  default:
    desc: List tasks grouped by area (alphabetical listing is `task -l`)
    silent: true
    cmds:
      - task --list-all --sort none

  # --- 1. Create (template only) ---

  new-repo:
    desc: Create a new repo from this template (NAME, PKG, DESC; created beside this repo)
    # new-repo.sh runs `gh repo create --clone`, which clones into the current directory. Run
    # from the repo root it would nest the new project inside the template, so the task runs one
    # level up and calls the script by absolute path.
    # Usage: task new-repo NAME=my-project PKG=my_project DESC="A cool new project"
    # Run it from inside this repo; the task moves to the parent itself.
    dir: '{{.ROOT_DIR}}/..'
    requires:
      vars: [NAME, PKG, DESC]
    cmds:
      - |
        if [ -f "{{.ROOT_DIR}}/.ade-template-version" ]; then
          echo "This repo was generated from the ADE template — new-repo belongs in the template itself." >&2
          exit 1
        fi
        bash "{{.ROOT_DIR}}/new-repo.sh" "{{.NAME}}" "{{.PKG}}" "{{.DESC}}" {{.VISIBILITY}}

  # --- 2. Environment ---

  install:
    desc: Setup venv and install dependencies
    cmds:
      - uv sync

  mcp:check:
    desc: MCP diagnostics — duplicate scopes, dead servers (see docs/mcp-servers.md)
    silent: true
    cmds:
      - |
        OUT=$(claude mcp list 2>&1); echo "$OUT"
        if echo "$OUT" | grep -q "defined in multiple scopes"; then
          echo "FAIL: MCP server duplicated across scopes — consolidate; per-endpoint OAuth tokens conflict"; exit 1
        fi
        if echo "$OUT" | grep -q "Failed to connect"; then
          echo "FAIL: an MCP server failed to connect — fix or remove it"; exit 1
        fi
        echo "MCP OK"

  # --- 3. Develop ---

  fmt:
    desc: Auto-format and apply fixable lint rules
    cmds:
      - uv run ruff format {{.SRC}} {{.TESTS}}
      - uv run ruff check --fix {{.SRC}} {{.TESTS}}

  lint:
    desc: Check formatting and lint rules (read-only)
    cmds:
      - uv run ruff format {{.SRC}} {{.TESTS}} --check
      - uv run ruff check {{.SRC}} {{.TESTS}}

  typecheck:
    desc: Type check with mypy
    cmds:
      - uv run mypy {{.SRC}}

  # --- 4. Test ---

  test:
    desc: Run tests with coverage
    cmds:
      - uv run pytest {{.TESTS}} --cov={{.SRC}}/{{.APP}} --cov-report=term-missing

  test:all:
    desc: Run tests including the slow scaffold gates
    cmds:
      - uv run pytest {{.TESTS}} -m "slow or not slow" --cov={{.SRC}}/{{.APP}} --cov-report=term-missing

  # --- 5. Gate ---

  # `check` is the contract between a developer's machine and CI:
  # .github/workflows/main.yml invokes exactly this target. Keep it CI-safe — openspec and
  # openlore are npm globals that runners do not install, so they belong in `verify`, not here.
  check:
    desc: All CI gates — lint, typecheck, tests, docs build (what main.yml runs)
    cmds:
      - task: lint
      - task: typecheck
      - task: test
      - task: docs:build

  pre-commit:
    desc: Run all pre-commit hooks
    cmds:
      - uv run pre-commit run --all-files

  verify:
    desc: Full local gate — check plus drift and spec validation (needs CHANGE)
    cmds:
      - task: check
      - task: lore:drift
      - task: spec:validate

  # --- 6. Docs ---

  docs:
    desc: Serve MkDocs locally
    cmds:
      - uv run mkdocs serve

  docs:build:
    desc: Build the docs strictly (what CI runs)
    cmds:
      - uv run mkdocs build -s

  # --- 7. Spec lifecycle (OpenSpec) ---
  # Alphabetical, per the listing convention. Workflow order is init, validate, status, archive.

  spec:archive:
    desc: Archive a completed OpenSpec change (merges deltas to main specs)
    deps: [spec:validate, lore:drift, test]
    cmds:
      - openspec archive {{.CHANGE}}

  spec:init:
    desc: Initialize OpenSpec in this project
    cmds:
      - openspec init --tools claude

  spec:status:
    desc: Show OpenSpec change status
    cmds:
      - openspec status --change {{.CHANGE}}

  spec:validate:
    desc: Validate the current OpenSpec change
    cmds:
      - openspec validate {{.CHANGE}}

  # --- 8. Drift and memory (OpenLore) ---

  lore:analyze:
    desc: Build call graph and structural digest
    cmds:
      - openlore analyze

  lore:drift:
    desc: Detect spec/code drift
    cmds:
      - openlore drift

  lore:mcp:
    desc: Start OpenLore MCP server (for agent orient() calls)
    cmds:
      - openlore mcp

  # --- 9. Work distribution (thin glue) ---
  # Alphabetical, per the listing convention. The pipeline runs dispatch, collect, sync-docs.

  collect:
    desc: Collect HANDOFF.md files from Orca worktrees (needs CHANGE)
    cmds:
      - uv run python scripts/collect_handoffs.py --change {{.CHANGE}}

  dispatch:
    desc: Parse OpenSpec tasks.md and emit work-order files (needs CHANGE)
    cmds:
      - uv run python scripts/dispatch_tasks.py --change {{.CHANGE}}

  sync-docs:
    desc: Run drift checks and print doc-updater instructions (needs CHANGE)
    cmds:
      - openlore drift
      - openspec validate {{.CHANGE}}
      - echo "Review handoffs/ for plan-relevant updates"
      - 'echo "Apply via: edit openspec/changes/{{.CHANGE}}/specs/ then openspec validate {{.CHANGE}}"'

  # --- 10. Template updates (generated repos) ---

  template:diff:
    desc: Show ADE template changes since this repo was generated
    cmds:
      - bash scripts/template_sync.sh diff

  template:sync:
    desc: Apply ADE template changes to infrastructure paths (never README/CLAUDE/src)
    cmds:
      - bash scripts/template_sync.sh apply
```

Update the `APP` var to match your package name. If cookiecutter-uv generated a `Makefile` or `justfile`, you can remove it or keep it alongside.

### 3. Initialize OpenSpec

```bash
openspec init --tools claude
```

This creates:
- `openspec/config.yaml` — project context, rules, constraints
- `openspec/changes/` — active change proposals
- `openspec/specs/` — archived (main) specs
- `.claude/commands/opsx/` — slash commands (`/opsx:propose`, `/opsx:apply`, `/opsx:archive`, etc.)

Edit `openspec/config.yaml` to include your tech stack and project rules:

```yaml
schema: spec-driven

context: |
  Tech stack: Python, uv, ruff, mypy, pytest
  Task runner: Taskfile (go-task)
  Docs: MkDocs
  Agent env: Orca ADE with isolated git worktrees
  We maintain backwards compatibility for all public APIs

rules:
  proposal:
    - Include rollback plan for risky changes
  specs:
    - Use Given/When/Then format for scenarios
    - Every requirement must have at least one testable scenario
  design:
    - Include data model and API surface for non-trivial changes
  tasks:
    - Break tasks into max 2-hour chunks
    - Each task must produce at least one test
```

### 4. Initialize OpenLore

```bash
# Write .openlore/config.json — required before analyze, which otherwise fails
# with "No openlore configuration found"
openlore init

# Build call graph and structural digest (no API key needed)
openlore analyze

# Optionally generate living specs (requires LLM/API key)
# openlore generate

# Verify it works
openlore drift
```

Drift detection is wired as a pre-commit hook by the `openlore-drift` entry in
`.pre-commit-config.yaml`, installed with `uv run pre-commit install` (step 7). Do **not** run
`openlore drift --install-hook` — it writes `.git/hooks/pre-commit` directly and overwrites the
pre-commit framework's shim, leaving two tools fighting over one hook file.

This creates:
- `.openlore/analysis/` — call graph SQLite DB, `CODEBASE.md` digest
- `.openlore/` — drift state, spec mappings
- Pre-commit hook that runs drift checks on commit

Add OpenLore MCP to your agent config so agents can call `orient()`. Claude Code reads
project-scoped servers from `.mcp.json` in the repo root:

```json
{
  "mcpServers": {
    "openlore": {
      "command": "openlore",
      "args": ["mcp"]
    }
  }
}
```

### 5. Add AGENTS.md

Create `AGENTS.md` in the repo root. This is what Orca agents read first when they start a worktree session:

```markdown
# AGENTS.md

## Project Overview

This project uses a four-component stack:
- OpenSpec for spec-driven planning (openspec/ directory)
- OpenLore for drift detection and architectural memory (.openlore/ directory)
- Orca ADE for isolated worktree execution
- Taskfile for all project commands (run `task -l` to see available tasks)

## Before You Start

1. Call `orient("<your task>")` via the OpenLore MCP tool if available.
2. Read the active OpenSpec change: `openspec/changes/<change-name>/`
3. Read `openspec/changes/<change-name>/specs/` for the requirements and scenarios.
4. Read `openspec/changes/<change-name>/tasks.md` for your assigned task.

## Rules

### Testing
- Write tests first (red-green-refactor).
- Every task must produce at least one test file.
- Run `task test` before finishing.

### Specs
- Do NOT edit files in `openspec/specs/` or `openspec/changes/*/specs/`.
- If you discover a spec needs updating, write the proposed change to `HANDOFF.md`.
- The doc-updater agent handles all spec updates.

### HANDOFF.md
At the end of your session, create `HANDOFF.md` in the worktree root.

Include only spec-relevant updates:
- Requirements that need adding, modifying, or removing
- Scenarios that are wrong or missing
- Design decisions that conflict with the spec
- New capabilities discovered during implementation

Do NOT include:
- Implementation details or code choices
- Style or formatting decisions
- Non-plan-changing refactors

### Quality
- Run `task lint` before committing.
- Run `task test` before committing.
- `openlore drift` runs automatically via pre-commit hook — fix drift before pushing.
- One task = one commit.

### When to Stop
- If the spec is wrong: stop, write to HANDOFF.md under `## Design Drift`, finish.
- If tests cannot pass due to a spec contradiction: stop, write to HANDOFF.md, finish.
- Do not improvise around spec gaps. Surface them.
```

### 6. Add thin-glue scripts

Create `scripts/dispatch_tasks.py`:

```python
#!/usr/bin/env python3
"""
Parse an OpenSpec change's tasks.md and emit individual work-order files.

Each work-order is a self-contained markdown file that an Orca agent
can receive as its prompt. Work-orders are written to work_orders/<change>/.

Usage:
    python scripts/dispatch_tasks.py --change <change-name>

The script does NOT create Orca worktrees directly. It prints the Orca CLI
command for each work-order (flags verified against onorca.dev/docs/cli/reference
and the installed binary, 2026-07-31). Requires `orca serve` or the Orca app
to be running.
"""

import argparse
import re
import sys
from pathlib import Path


def parse_tasks(tasks_md: Path) -> list[dict]:
    """Parse tasks.md into a list of {id, title, body} dicts.

    Expects GitHub-flavored markdown task lists:
        - [ ] Task title
          Description lines...

    Also handles milestone headers (## Milestone N).
    """
    if not tasks_md.exists():
        print(f"Error: {tasks_md} not found", file=sys.stderr)
        sys.exit(1)

    content = tasks_md.read_text()
    tasks = []
    current_milestone = "default"
    current_task = None

    for line in content.splitlines():
        # Milestone header
        milestone_match = re.match(r"^##\s+(.+)$", line)
        if milestone_match:
            current_milestone = milestone_match.group(1).strip()
            continue

        # Task line
        task_match = re.match(r"^-\s+\[[ xX]\]\s+(.+)$", line)
        if task_match:
            # Save previous task
            if current_task:
                tasks.append(current_task)

            current_task = {
                "milestone": current_milestone,
                "title": task_match.group(1).strip(),
                "body": [],
                "done": "[x" in line or "[X" in line,
            }
        elif current_task and line.strip() and not line.startswith("#"):
            current_task["body"].append(line)

    if current_task:
        tasks.append(current_task)

    return tasks


def emit_work_orders(tasks: list[dict], change: str, output_dir: Path) -> list[Path]:
    """Write one work-order file per task."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for i, task in enumerate(tasks, 1):
        task_id = f"task-{i:03d}"
        filename = f"{task_id}.md"
        filepath = output_dir / filename

        lines = [
            f"# Work Order: {task['title']}",
            "",
            f"**Change**: {change}",
            f"**Milestone**: {task['milestone']}",
            f"**Task ID**: {task_id}",
            "",
            "## Objective",
            "",
            task["title"],
            "",
        ]

        if task["body"]:
            lines += ["## Context", ""]
            lines += task["body"]
            lines.append("")

        lines += [
            "## Requirements",
            "",
            "1. Read the spec file: `openspec/changes/" + change + "/specs/` for requirements and scenarios.",
            "2. Write tests first (red-green-refactor).",
            "3. Implement the minimum to satisfy the spec scenario.",
            "4. Run `task lint && task test` before finishing.",
            "5. Write `HANDOFF.md` in the worktree root with any spec-relevant updates.",
            "",
            "## Agent Instructions",
            "",
            '- Call `orient("' + task["title"] + '")` via OpenLore MCP if available.',
            "- Do NOT edit files in `openspec/`.",
            "- One commit per task.",
            "- If the spec is wrong, write to HANDOFF.md and stop.",
            "",
        ]

        filepath.write_text("\n".join(lines))
        paths.append(filepath)

    return paths


def main():
    parser = argparse.ArgumentParser(description="Dispatch OpenSpec tasks as Orca work-orders")
    parser.add_argument("--change", required=True, help="OpenSpec change name")
    parser.add_argument(
        "--output",
        default="work_orders",
        help="Output directory for work-order files (default: work_orders)",
    )
    parser.add_argument(
        "--agent",
        default="claude",
        help="Orca agent id to launch in each worktree (default: claude)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "Orca repo selector (id:<id>, name:<name>, or path:<path>). "
            "Defaults to path:<cwd>. Orca only infers the repo when called from "
            "inside an Orca-managed worktree, so the selector is emitted explicitly."
        ),
    )
    args = parser.parse_args()

    tasks_md = Path("openspec/changes") / args.change / "tasks.md"
    tasks = parse_tasks(tasks_md)

    if not tasks:
        print(f"No tasks found in {tasks_md}")
        sys.exit(0)

    output_dir = Path(args.output) / args.change
    paths = emit_work_orders(tasks, args.change, output_dir)

    print(f"Emitted {len(paths)} work-orders to {output_dir}/")
    print()
    repo_selector = args.repo or f"path:{Path.cwd()}"

    print("Orca dispatch commands (requires `orca serve` or the Orca app running):")
    print()
    for p in paths:
        print(
            f"  orca worktree create --name {p.stem} --repo {repo_selector}"
            f' --agent {args.agent} --prompt "$(cat {p})" --setup run --json'
        )
        print()

    print("After all worktrees complete, run:")
    print(f"  task collect CHANGE={args.change}")
    print(f"  task sync-docs CHANGE={args.change}")


if __name__ == "__main__":
    main()
```

Create `scripts/collect_handoffs.py`:

```python
#!/usr/bin/env python3
"""
Collect HANDOFF.md files from Orca worktrees into a central directory.

Orca creates worktrees as subdirectories. This script scans a configurable
directory for HANDOFF.md files and copies them to handoffs/<change>/.

Usage:
    python scripts/collect_handoffs.py --change <change-name>

Environment:
    ORCA_WORKTREES_DIR  Directory where Orca stores worktrees.
                        Defaults to the git worktree list output.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_worktrees() -> list[Path]:
    """Get worktree paths via git worktree list."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("Error: could not list git worktrees", file=sys.stderr)
        return []

    worktrees = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1])
            if path.exists():
                worktrees.append(path)

    return worktrees


def collect_handoffs(worktrees: list[Path], change: str, output_dir: Path) -> list[Path]:
    """Find HANDOFF.md in each worktree and copy to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    collected = []

    for wt in worktrees:
        handoff = wt / "HANDOFF.md"
        if not handoff.exists():
            continue

        # Name the file after the worktree directory
        name = wt.name
        dest = output_dir / f"{name}.md"
        shutil.copy2(handoff, dest)
        collected.append(dest)
        print(f"Collected: {dest}")

    return collected


def summarize_handoffs(handoffs: list[Path], change: str) -> str:
    """Produce a summary for the doc-updater agent."""
    if not handoffs:
        return f"No HANDOFF.md files found for change '{change}'."

    lines = [
        f"# Handoff Summary: {change}",
        "",
        f"Collected {len(handoffs)} handoff(s).",
        "",
        "## Files",
        "",
    ]
    for h in handoffs:
        lines.append(f"- [{h.name}]({h})")

    lines += [
        "",
        "## Doc-Updater Instructions",
        "",
        "1. Read each handoff file above.",
        "2. For each spec-relevant update, edit the corresponding file in:",
        f"   `openspec/changes/{change}/specs/`",
        "3. Run `openspec validate " + change + "` to check format.",
        "4. Run `openlore drift` to check for new drift.",
        "5. Ignore implementation details — only apply plan-relevant changes.",
        "6. If a handoff contains `## Design Drift`, flag for human review.",
        "",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Collect HANDOFF.md files from Orca worktrees")
    parser.add_argument("--change", required=True, help="OpenSpec change name")
    parser.add_argument(
        "--output",
        default="handoffs",
        help="Output directory for collected handoffs (default: handoffs)",
    )
    parser.add_argument(
        "--worktrees-dir",
        default=os.environ.get("ORCA_WORKTREES_DIR"),
        help="Directory containing Orca worktrees (default: auto-detect via git)",
    )
    args = parser.parse_args()

    if args.worktrees_dir:
        wt_root = Path(args.worktrees_dir)
        # Sorted: iterdir() order is filesystem-dependent, which would make the collected
        # file order and the SUMMARY.md listing differ between machines.
        worktrees = sorted(d for d in wt_root.iterdir() if d.is_dir()) if wt_root.exists() else []
    else:
        worktrees = find_worktrees()

    if not worktrees:
        print("No worktrees found. Are you running this from the repo root?")
        sys.exit(1)

    output_dir = Path(args.output) / args.change
    handoffs = collect_handoffs(worktrees, args.change, output_dir)

    if handoffs:
        summary = summarize_handoffs(handoffs, args.change)
        summary_path = Path(args.output) / args.change / "SUMMARY.md"
        summary_path.write_text(summary)
        print(f"\nSummary written to {summary_path}")
        print(f"\nNext step: task sync-docs CHANGE={args.change}")
    else:
        print("\nNo HANDOFF.md files found in any worktree.")


if __name__ == "__main__":
    main()
```

Create a `HANDOFF.md` template at `templates/HANDOFF.md`:

```markdown
# HANDOFF

**Worktree**: <!-- worktree/branch name -->
**Change**: <!-- OpenSpec change name -->
**Task ID**: <!-- e.g. task-001 -->
**Date**: <!-- YYYY-MM-DD -->

## Spec Updates

<!-- List any requirements that need adding, modifying, or removing.
     Reference the spec file and section. -->

### Added Requirements
<!-- New requirements discovered during implementation -->

### Modified Requirements
<!-- Existing requirements that need correction -->

### Removed Requirements
<!-- Requirements that turned out to be unnecessary -->

## Design Drift

<!-- If the spec or design doc is wrong, describe the discrepancy here.
     The doc-updater agent will flag this for human review. -->

## New Scenarios

<!-- Any Given/When/Then scenarios that should be added to the spec -->

## Notes for Doc-Updater

<!-- Anything the doc-updater agent needs to know.
     Do NOT include implementation details, code choices, or style decisions. -->
```

### 7. Run first validation

```bash
# Verify OpenSpec is initialized
openspec --version
openspec list --specs

# Verify OpenLore is working
openlore drift

# Verify Taskfile
task -l

# Verify pre-commit
uv run pre-commit install
uv run pre-commit run --all-files

# Verify tests pass
task test

# Commit the setup
git add .
git commit -m "Add OpenSpec, OpenLore, AGENTS.md, and thin-glue scripts"
```

## Target File Tree

After bootstrap, your repo should look like this:

```
your-project/
├── .github/workflows/          # CI (from cookiecutter-uv)
├── .claude/
│   ├── commands/opsx/          # OpenSpec slash commands
│   └── settings.json           # Permission allowlist for agent sessions
├── .env.example                # Documented env vars, values empty
├── .mcp.json                   # MCP config (OpenLore) — project-scoped servers
├── .openlore/
│   └── analysis/               # Call graph, CODEBASE.md digest
├── .pre-commit-config.yaml     # ruff, mypy, OpenLore drift hook
├── .python-version             # Interpreter pin for uv
├── AGENTS.md                   # Agent operating contract (Orca worktree sessions)
├── CLAUDE.md                   # Claude Code session contract, PHI guardrails
├── HANDOFF.md                  # (created per-worktree session, not committed)
├── README.md                   # This file
├── Taskfile.yml                # Project commands + thin-glue targets
├── WORKFLOW.md                 # Order of operations: plan → dispatch → collect → archive
├── .ade-template-version       # Template commit this repo was generated from
├── docs/                       # MkDocs documentation
│   ├── adr/                    # Architecture decision records (append-only)
│   ├── ci-lessons.md           # Dated failure classes; read before editing CI
│   └── contracts/              # publishes.md / consumes.md
├── handoffs/                   # Collected HANDOFF.md files (gitignored)
├── openspec/
│   ├── config.yaml             # Project context and rules
│   ├── changes/                # Active change proposals
│   │   └── <change-name>/
│   │       ├── proposal.md
│   │       ├── design.md
│   │       ├── tasks.md
│   │       └── specs/
│   │           └── <capability>/
│   │               └── spec.md
│   └── specs/                  # Archived (main) specs
├── pyproject.toml              # uv, ruff, mypy config
├── scripts/
│   ├── dispatch_tasks.py        # Parse tasks.md → work-orders
│   ├── collect_handoffs.py     # Gather HANDOFF.md from worktrees
│   └── template_sync.sh        # Template drift: diff / apply
├── src/
│   └── <package_name>/         # Your Python package
│       └── py.typed            # PEP 561 marker
├── templates/
│   └── HANDOFF.md              # Handoff template
├── tests/                      # pytest tests
│   └── scaffold/               # Nine gates validating this scaffold
├── uv.lock
└── work_orders/                # Emitted work-order files (gitignored)
```

Add these to `.gitignore`:

```
# openlore analysis artifacts
.openlore/

# Thin-glue working state
work_orders/
handoffs/

# HANDOFF.md (per-worktree, not committed; templates/HANDOFF.md stays tracked)
/HANDOFF.md
```

`/HANDOFF.md` is anchored to the repo root on purpose — an unanchored `HANDOFF.md` would also
ignore the tracked `templates/HANDOFF.md`.

## Daily Workflow

The end-to-end loop for one OpenSpec change:

### 1. Create a change proposal

```bash
/opsx:propose "Add user authentication with JWT"
```

Or via CLI:

```bash
openspec new change add-user-auth
```

Then write `proposal.md`, `design.md`, `specs/<capability>/spec.md`, and `tasks.md` in the change directory. Use `openspec validate add-user-auth` to check format.

### 2. Plan quality gate

Before dispatching tasks, verify the plan is MECE and testable:

- [ ] Every requirement in `spec.md` has at least one `#### Scenario:` block (Given/When/Then)
- [ ] `openspec validate <change>` passes
- [ ] `tasks.md` tasks are atomic (one task = one commit, max ~2 hours)
- [ ] Each task maps to at least one spec scenario
- [ ] No two tasks overlap in scope (mutually exclusive)
- [ ] All spec scenarios are covered by at least one task (collectively exhaustive)
- [ ] Task dependencies are explicit (note blocking tasks in the task description)

If any check fails, revise the plan before dispatching.

### 3. Dispatch work-orders

```bash
task dispatch CHANGE=add-user-auth
```

This parses `openspec/changes/add-user-auth/tasks.md` and writes one work-order file per task to `work_orders/add-user-auth/`. It prints the Orca dispatch command for each.

### 4. Create Orca worktrees and assign agents

Run the commands `task dispatch` printed. Each is a single invocation — worktree, agent, and prompt in one shot. `orca serve` (headless) or the Orca app must be running:

```bash
orca worktree create --name task-001 --repo path:$PWD --agent claude --prompt "$(cat work_orders/add-user-auth/task-001.md)" --setup run --json
```

Flag notes, verified against `orca worktree create --help`:

- `--repo` is emitted explicitly because Orca only infers the repo when called from inside an Orca-managed worktree. Accepts `id:<id>`, `name:<name>`, or `path:<path>`.
- `--prompt` sends the work-order to the agent launched by `--agent` as its initial work.
- `--setup run` forces the repo's setup hooks so the worktree has a working venv.
- `--json` emits the worktree path plus the agent terminal handle — read it from `result.agentTerminalHandle`, falling back to `result.startupTerminal.handle` on older runtimes.

The agent will:
1. Read AGENTS.md (operating contract)
2. Call `orient()` via OpenLore MCP if available
3. Read the spec and tasks for the change
4. Write tests first (TDD)
5. Implement
6. Run `task lint && task test`
7. Write `HANDOFF.md` with any spec-relevant updates
8. Commit

### 5. Collect handoffs

After all worktree sessions complete:

```bash
task collect CHANGE=add-user-auth
```

This gathers `HANDOFF.md` files from all worktrees into `handoffs/add-user-auth/` and writes a `SUMMARY.md` with instructions for the doc-updater.

### 6. Run the doc-updater

Open a fresh Orca worktree (or Claude Code session) with the doc-updater prompt:

```
You are the doc-updater agent. Read handoffs/add-user-auth/SUMMARY.md
and each handoff file it references. Apply ONLY plan-relevant updates
to openspec/changes/add-user-auth/specs/. Ignore implementation details.
If any handoff contains ## Design Drift, flag it for human review and
do not apply those changes. Run `openspec validate add-user-auth` after
making changes.
```

### 7. Verify and archive

```bash
# Full quality gate
task verify CHANGE=add-user-auth

# If all gates pass, archive (merges deltas to main specs)
task spec:archive CHANGE=add-user-auth

# Merge the winning worktree(s)
# Use Orca's diff review UI to pick the best changes
```

### 8. Repeat

Start the next change. OpenLore's `orient()` will include the newly archived specs, giving the next round of agents up-to-date context.

## Quality Gates

These must pass before merge or archive:

| Gate | Command | What it checks |
|---|---|---|
| **CI gate** | `task check` | lint + typecheck + tests + docs build — exactly what CI runs |
| Lint | `task lint` | ruff format check + ruff check (read-only; `task fmt` applies fixes) |
| Type check | `task typecheck` | mypy |
| Tests | `task test` | pytest with coverage, floor 80 (scaffold gates 7 and 9 excluded as `slow`) |
| Full tests | `task test:all` | adds the git-sandbox and fresh-clone scaffold gates |
| Docs | `task docs:build` | strict MkDocs build — broken links fail |
| Drift | `task lore:drift` | OpenLore spec/code drift detection |
| Spec validation | `task spec:validate` | OpenSpec format and scenario validation |
| Pre-commit | `task pre-commit` | All pre-commit hooks (includes drift) |
| MCP | `task mcp:check` | duplicate MCP scopes, dead servers |

`task check` is the contract between your machine and CI — `.github/workflows/main.yml` invokes
that exact target, and `tests/scaffold/cat4_ci_contract.py` fails if a workflow ever runs
something else. `task verify CHANGE=<name>` adds drift and spec validation on top; use it before
any merge. The three shell gates (`tests/scaffold/cat{2,4,7}_*.sh`) need the full local
toolchain and are run deliberately, not by `check`.

## Template updates

A repo generated from this template shares no git history with it, so improvements do not arrive
on their own. `bootstrap.sh` records the template commit in `.ade-template-version`, and two
targets work from that baseline:

```bash
task template:diff   # what changed in the template since this repo was generated
task template:sync   # apply those changes to infrastructure paths
```

`template:sync` touches only what the template owns — `.github/`, `Taskfile.yml`,
`.pre-commit-config.yaml`, `bootstrap.sh`, `scripts/`, `tests/scaffold/` — and never `README.md`,
`CLAUDE.md`, `AGENTS.md`, `pyproject.toml`, `src/`, `docs/` or `openspec/`, which belong to the
repo once generated. It applies with `--3way`, so a conflict leaves markers in the working tree
rather than silently dropping a change. Run `task check` afterwards.

**Retrofitting an existing repo is not supported.** `gh repo create --template` only creates new
repositories; there is no equivalent of copier's `copier copy` into a populated directory. An
existing repo can adopt the template only by recording a baseline by hand
(`git ls-remote <template> main | cut -f1 > .ade-template-version`) and running `task
template:sync`, which will conflict heavily on a repo that never matched the template.

## Troubleshooting

### Orca CLI flags have changed

Orca ships stable releases roughly daily, so the CLI surface moves. Pin a known-good version rather than tracking latest. If `orca worktree create` fails, check:

```bash
orca --help
orca worktree create --help
```

Two known version-sensitive points:

- **JSON result shape** varies across runtime versions — the agent terminal handle appears as either `result.agentTerminalHandle` or `result.startupTerminal.handle`. Tolerate both when parsing.
- **`orca orchestration worker-start`** exists only in recent builds. Older builds use `orchestration task-create` + `dispatch --inject` for the same effect.

The dispatch script prints commands but does not execute them. See [docs/ade-compare.md](docs/ade-compare.md) for the verified CLI surface and the evidence behind these flags.

### OpenLore generate fails (no API key)

`openlore generate` requires an LLM provider. `openlore analyze` and `openlore drift` do not. If you don't have an API key set up, skip `generate` — the call graph, drift detection, and MCP `orient()` (with BM25 fallback) still work without it.

### HANDOFF.md is missing from a worktree

If an agent finished without writing `HANDOFF.md`:
1. Check if the agent made spec-relevant changes (it may have had nothing to report — that's fine).
2. If it did change behavior without documenting it, review the diff manually and create the handoff yourself.
3. Add a note to AGENTS.md reinforcing the handoff requirement if agents repeatedly skip it.

### Spec drift detected after a session

If `openlore drift` reports drift after a worktree session:
1. Check `handoffs/` for a HANDOFF.md that addresses the drifted area.
2. If the handoff exists, the doc-updater should apply it.
3. If no handoff exists, the agent missed it — review the diff and update specs manually.
4. Do not archive the change until drift is resolved or documented.

### Tests are missing for a task

If a work-order lands without tests:
1. Do not merge the worktree.
2. Send the agent back with: "No tests found for this task. Write tests first (red-green-refactor), then re-submit."
3. If the task genuinely doesn't need tests (e.g. docs-only change), document the exception in HANDOFF.md.

### openspec validate fails

Common causes:
- `proposal.md` missing `## Why` or `## What Changes` sections
- `spec.md` missing `## ADDED/MODIFIED/REMOVED Requirements` delta header
- A requirement missing `#### Scenario:` block
- Scenarios not in Given/When/Then format

Run `openspec show <change> --json --deltas-only` to see what was parsed and fix the format.
