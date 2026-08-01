# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

pulse — Patient unified ledger of state and events

The package lives in `src/pkg_pulse/`.

## Commands

```bash
task              # list commands, grouped by area
task check        # lint, typecheck, tests, docs build — exactly what CI runs
task fmt          # apply formatting and fixable lint rules
task test:all     # includes the slow scaffold gates
task pre-commit   # all hooks
```

Thin-glue targets take go-task variable syntax: `task dispatch CHANGE=add-auth`. Passing the
change as a flag instead exits 2 with `unknown flag`.

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
