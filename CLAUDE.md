# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

repo-ade is a **GitHub template repository**. Its product is its own structure, tooling wiring,
and documented bootstrap — not the two-function package under `src/`. Work here is judged by what
a *generated* repo receives, so the question for any change is "does this survive
`gh repo create --template`?"

Generated with `./new-repo.sh <repo-name> <package_name> "<description>"`, which creates the repo
from the template, clones it, and runs `bootstrap.sh` to rename the package, re-init OpenSpec and
OpenLore, commit, and push.

## Commands

```bash
task              # list tasks grouped by area, in workflow order
task check        # lint + typecheck + tests + docs build — exactly what main.yml runs
task verify CHANGE=<name>   # fuller local gate: check + lore:drift + spec:validate
task test         # pytest with coverage (slow gates excluded)
task test:all     # adds the git-sandbox and fresh-clone gates
task lint         # ruff format --check + ruff check (read-only)
task fmt          # apply formatting and fixable lint rules
task typecheck    # mypy
task pre-commit   # all 11 hooks
task mcp:check    # MCP diagnostics: duplicate scopes, dead servers
task template:diff / template:sync   # ADE template drift (generated repos only)
task new-repo NAME=x PKG=x_pkg DESC="..."   # new repo from this template (template only)
```

Bare `task` lists by area in workflow order; `task -l` sorts alphabetically and scatters the
grouping, so prefer `task` when browsing.

```bash
```

Thin-glue targets take go-task **variable** syntax, never flags — `task dispatch CHANGE=add-auth`.
Passing the change as a `--change <name>` flag instead exits 2 with `unknown flag`.

```bash
uv run pytest tests/scaffold/cat5_glue_logic.py -v                    # one gate
uv run pytest tests/scaffold/cat5_glue_logic.py::test_parse_tasks_titles_in_order -v   # one test
uv run pytest tests -m slow                                           # slow gates only
REGEN=1 uv run pytest tests/scaffold/cat9_golden_workflow.py          # regenerate goldens
./tests/scaffold/cat2_toolchain.sh                                    # shell gates: cat2, cat4, cat7
```

## Architecture

**Four tools, thin glue.** OpenSpec owns the change lifecycle (`openspec/`), OpenLore owns drift
detection and the `orient()` MCP tool (`.openlore/`, `.mcp.json`), Orca owns worktree execution,
and this repo contributes only `Taskfile.yml`, two scripts, and `AGENTS.md`. No orchestration
runtime — see the stack table in `README.md`.

**The daily loop:** OpenSpec change → `scripts/dispatch_tasks.py` parses `tasks.md` into one
work-order file per task → Orca worktrees run agents → each writes `HANDOFF.md` →
`scripts/collect_handoffs.py` gathers them into `handoffs/<change>/SUMMARY.md` → a doc-updater
applies spec changes → `task spec:archive` (gated on validate + drift + test).

**Two agent contracts, both binding, different readers.** `AGENTS.md` governs agents inside Orca
worktrees (do not edit specs, write HANDOFF.md, one task one commit). This file governs Claude
Code sessions in the repo root.

### Delivery classes — the recurring failure mode

`gh repo create --template` copies **only committed content**. Every bootstrap bug this repo has
had came from forgetting that:

- **Gitignored** (`.openlore/`) never arrives → `bootstrap.sh` runs `openlore init`.
- **Empty directories** (`openspec/specs/`, `openspec/changes/archive/`) cannot be tracked by git
  at all → `bootstrap.sh` recreates them with `mkdir -p`. Without them the `openlore-drift` hook
  hard-fails with "No specs found".
- **Non-`.py/.yml/.yaml/.toml/.md/.json/.sh` files** are skipped by `bootstrap.sh`'s
  find-and-replace, so they keep the template's package name.

Before adding anything to the template, classify it. `tests/scaffold/cat1_structure.py` encodes
these classes and will fail if a new path is unclassified.

### The scaffold gate suite

`tests/scaffold/` holds nine gates that validate the scaffold itself; `tests/test_foo.py` is the
only test of the package. Gates are numbered by concern (structure → toolchain → config →
commands → glue → edges → hooks → docs → end-to-end) and split by execution environment: `.py`
gates are CI-safe, `.sh` gates need the full local toolchain. Gate 4 has both halves.

Three couplings worth knowing before editing:

- **`task check` is the CI contract.** `.github/workflows/main.yml` invokes it;
  `cat4_ci_contract.py` asserts every workflow command resolves to a defined target or an
  installed tool. Keep `check` free of `openspec`/`openlore` — runners do not install them.
- **README is the spec.** `cat8_docs_consistency.py` diffs the README's Taskfile and script
  snippets against the real files **byte-for-byte**. Editing `Taskfile.yml` or `scripts/*.py`
  means re-syncing the corresponding fenced block in `README.md`.
- **Gate filenames need the `python_files` pattern.** `cat[0-9]_*.py` matches no pytest default;
  `pyproject.toml` widens `python_files` so `task test` collects them. Without it the suite
  passes having run nothing.

Fixtures use `.fixture`/`.golden` suffixes, not `.md`, so a markdown-hygiene hook cannot mistake
test data for stray documentation.

## Data sensitivity (PHI)

This is a healthcare data platform template. These rules are restated here rather than inherited,
because this file ships to every generated repo:

- No PHI in logs, commits, test fixtures, error messages, or docs. Synthetic data only.
- Never send PHI to an external service — web search, third-party APIs, MCP tools, published
  artifacts.
- Flag any code path where PHI could reach a logger or leave the process, even if the current
  inputs are synthetic.
- Fixtures and goldens under `tests/scaffold/data/` are committed and world-readable. They must
  stay synthetic.

## Conventions

- **No live network in tests.** CI has no secrets by default; the fresh-clone gate clones from
  the local path, never a remote.
- **Fix the template, never the generated repo.** A bug found downstream is a template bug.
- **Every addition lands with the gate that enforces it** — a convention no gate checks is how
  this repo shipped a CI that failed for a week.
- Ship changes green: `task check` and the three shell gates pass before commit, and CI is
  confirmed green on main afterwards (`gh run watch`).
