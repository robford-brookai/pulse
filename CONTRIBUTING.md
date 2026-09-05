# Contributing to pulse

## Owner

**Owner: Rob Ford** (GitHub [@robford-brookai](https://github.com/robford-brookai)). Ask the owner directly on Slack; a dedicated channel has not been named yet.

## Development Workflow

```bash
task install
task check      # must pass before every commit; it is what CI runs
```

`task fmt` applies the formatting and lint fixes that `task lint` only reports.

## Pre-commit Hooks

Pre-commit hooks run `ruff` and `openlore drift` on every commit. A hook that rewrites a file
fails the commit by design — re-stage and commit again. Type checking is not a pre-commit hook:
it runs via `task check` (`task typecheck`), the same gate CI runs.

## Before Making Changes

Read `AGENTS.md` before making changes as an agent, and `CLAUDE.md` for the session contract.
