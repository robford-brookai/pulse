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

**This is enforced.** `task collect` fails if a worktree has commits and no `HANDOFF.md`. A
worktree with no commits and no receipt is simply one that has not started; commits without a
receipt is work that happened and left no record of what was done or whether the spec held, which
also makes it invisible to `doc_update`. Write one even when there is nothing to report — "no
spec updates, no drift" is a complete and useful receipt.

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

- Run `task check` before committing — lint, typecheck, tests, docs build. This is exactly what
  CI runs, so a green `check` means a green pipeline.
- `task fmt` applies the formatting and fixable lint rules that `task lint` only reports.
- `openlore drift` runs automatically via pre-commit hook — fix drift before pushing.
- One task = one commit.

### When to Stop

- If the spec is wrong: stop, write to HANDOFF.md under `## Design Drift`, finish.
- If tests cannot pass due to a spec contradiction: stop, write to HANDOFF.md, finish.
- Do not improvise around spec gaps. Surface them.
