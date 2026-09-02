# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

pulse — Patient unified ledger of state and events.

The package lives in `src/pkg_pulse/`. It is currently a placeholder (`foo.py`): the substance of
this repo today is the agent development environment (ADE) scaffold and the design docs it will be
built from.

Two doc trees, split by concern — `design/` is what we are building, `docs/` is how this repo runs:

- `design/platform/` — the target architecture: event envelope, state catalog, Snowflake landing,
  Twenty data model, app scaffold, clinic rules engine. Read these before implementing anything in
  the ledger domain.
- `design/migration/` — legacy to PULSE: RPC object-model assessment, ledger backfill plan, Mongo
  archaeology, OCEAN absorption, genesis and cutover.
- `design/delivery/` — program execution: S1 work orders, runtime readiness.
- `docs/process/` — how the ADE workflow itself operates: the work-order dispatch template that
  `WORKFLOW.md` references, and the workflow drift review.
- `docs/adr/`, `docs/contracts/`, `docs/ci-lessons.md`, `docs/mcp-servers.md` — repo infrastructure.

Generated from the [repo-ade](https://github.com/robford-brookai/repo-ade) template
(`.ade-template-version` stamps the source commit). Template fixes come down via
`task template:diff` / `task template:sync`, which never touch README, CLAUDE.md, or `src/`.
Fix a template-level bug in the template, not here — a fix applied downstream reaches nobody else.

## Commands

```bash
task              # list commands, grouped by area, in workflow order
task check        # lint, typecheck, tests, Twenty app suite, docs build — exactly what CI runs
task fmt          # apply formatting and fixable lint rules
task test:all     # includes the slow scaffold gates (git sandbox, fresh-clone uv sync)
task verify CHANGE=<id>   # check + openlore drift + openspec validate
task pre-commit   # all hooks
```

Single test or gate:

```bash
uv run pytest tests/scaffold/cat5_glue_logic.py
bash tests/scaffold/cat2_toolchain.sh      # gates 2, 4, 7 are shell scripts, run directly
```

Thin-glue targets take go-task variable syntax: `task dispatch CHANGE=add-auth`. Passing the change
as a flag instead exits 2 with `unknown flag` — go-task does not accept flag-style args.

## Architecture: four tools, thin glue

No orchestration framework. Each tool owns a layer; a few scripts and `AGENTS.md` connect them.

- **OpenSpec** (`openspec/`) — change lifecycle: proposal → design → specs → tasks → archive.
  `openspec/specs/` is the accumulated baseline, written only by archiving a change.
- **OpenLore** (`.openlore/`, MCP server in `.mcp.json`) — call graph, drift detection, `orient()`.
  `openlore drift` is a pre-commit hook.
- **Orca ADE** — isolated git worktrees, one per task, parallel agent execution, diff review.
- **go-task** (`Taskfile.yml`) — every command. Areas are ordered by when you reach them, so the
  default target lists with `--sort none`.

Glue: `scripts/dispatch_tasks.py` (tasks.md → work-order files), `scripts/collect_handoffs.py`
(worktree HANDOFF.md files → `handoffs/<change>/SUMMARY.md`), `templates/HANDOFF.md`.

`WORKFLOW.md` is the operating workflow, and its YAML block is the source of truth — the prose and
mermaid sections are projections that regenerate from it, never hand-edited. It defines the step
graph (propose → validate → sync_linear → dispatch → execute → collect → doc_update → verify →
merge → archive), the four gates, and a `state_resolution` order an agent uses to compute which
step a change is at. Read it before touching dispatch behavior.

`AGENTS.md` is the binding contract for agents in worktrees: tests first, one task = one commit,
never edit spec files — write proposed spec changes to `HANDOFF.md` and let the doc-updater apply
them.

## Scaffold gates

`tests/scaffold/cat1..cat9` validate the repo's own structure and wiring, not the library:
structure → toolchain → config → command/CI contract → glue logic → edge cases → hooks → docs
consistency → golden end-to-end. They encode real past failures; `docs/ci-lessons.md` holds the
residue that no gate can express. **Read `docs/ci-lessons.md` before editing a workflow,
`Taskfile.yml`, or `bootstrap.sh`.** A new lesson that can be expressed as a gate belongs in
`tests/scaffold/`, not in that file.

Constraints these gates enforce, which are easy to break by accident:

- `.github/workflows/main.yml` must run exactly `task check`, and every `run:` command must resolve
  to a defined Taskfile target or a tool some step installs (`cat4_ci_contract.py`).
- `openspec` and `openlore` are npm globals CI runners do not have — keep them out of `task check`;
  they belong in `task verify` (`docs/contracts/consumes.md`).
- When CI grows a step, add it to `check`. The contract is true by name only otherwise.
- Scaffold gate files are named `cat[0-9]_*.py`, matched via `python_files` in `pyproject.toml`.
  Renaming them off that pattern makes pytest silently collect nothing.
- A gate must hold in a fresh clone of the committed tree, not just a bootstrapped working copy.
  Directories that must exist ship a tracked `.gitkeep`; anything gitignored is recreated by
  `bootstrap.sh`.
- Sort before iterating any directory whose order reaches output — golden tests flake otherwise.
- Placeholders in committed docs are inline code, never link syntax: `mkdocs build -s` treats a
  broken link as an error.

## Coordinator standing orders (the agent on main)

The human's role in the change cycle is review-and-merge, nothing else. Every gate is tool-run;
the human's only check surface is ordinary PR review. Tasks tagged destructive or prod-touching
never enter a worktree — they are tracked as GitHub issues and run attended after their runbook
PR merges (WORKFLOW.md `live_execution`). `<id>` is the change named in the command — tooling
takes `CHANGE=` explicitly and resolves state per change (design.md decision 9, `billing-connector`:
two changes can be in flight at once, so `<id>` is never inferred from `openspec/changes/`'s
directory listing). Resolve it once per command and fill it into every subsequent one.

- **After each PR merge you observe or perform** (the merge commit is `<sha>` on main):
  `task checkoff CHANGE=<id> COMMIT=1 COMMIT_SHA=<sha>` — then `task check` and push, per
  `main_access`. Batch is fine: omit `COMMIT_SHA` to sweep everything merged so far. The flip
  opens the next wave, so follow with `task dispatch CHANGE=<id>`.
- **After `task linear:sync CHANGE=<id> APPLY=1`**: commit the `[DNA-nnn]` id tokens it wrote
  into tasks.md (mechanical, `main_access`-eligible).
- **When the plan needs amending mid-change** (new task, widened scope, changed dep): branch,
  amend tasks.md, run `task replan CHANGE=<id>` until green, open a small PR. Never push a plan
  amendment directly to main — checkbox state and id tokens are the only tasks.md content
  eligible there.
- **When a wave completes**: `task collect CHANGE=<id>`, then commit
  `handoffs/<id>/SUMMARY.md` — it is the tracked receipt record.
- Never ask the human to run a gate, comment a gate, or construct a command; hand them PRs to
  review and merge, pre-filled commands otherwise.

## Data sensitivity (PHI)

- No PHI in logs, commits, test fixtures, error messages, or docs. Synthetic data only.
- Never send PHI to an external service — web search, third-party APIs, MCP tools, published
  artifacts.
- Flag any code path where PHI could reach a logger or leave the process, even if the current
  inputs are synthetic.

## Conventions

- `task check` is the contract between this machine and CI. Green locally means green in CI.
- No live network in tests; CI has no secrets by default.
- Specs are owned by the doc-updater: write proposed changes to `HANDOFF.md`, per `AGENTS.md`.
- `docs/adr/` is append-only; a superseded decision gets a status flip and a new ADR.
- Work reaches `main` by PR. Two exceptions, defined with their conditions under `main_access` in
  `WORKFLOW.md`: mechanical state updates carrying no reviewable decision, and repairing a red
  main. Merge with a merge commit, not a squash, whenever a branch carries imported history.
- Cross-repo integration goes through `docs/contracts/publishes.md` and `consumes.md` — a published
  Snowflake object, API, or released package. Never side-clone another repo into this one.
- **Ad-hoc markdown goes in `.planning/`** — status reports, analyses, one-off summaries, as
  `.planning/reports/YYYY-MM-DD-topic.md`. A loose `STATUS.md` or `NOTES.md` at the repo root is
  blocked on write by a `PreToolUse` hook, so choosing the path afterwards means redoing the file.
  The trees that already have a home keep it: `design/` for program and architecture docs, `docs/`
  for published pages, `openspec/` `work_orders/` `handoffs/` for the ADE workflow, and
  `HANDOFF.md` at a worktree root.
