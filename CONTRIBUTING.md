# Contributing to pulse

```bash
task install
task check      # must pass before every commit; it is what CI runs
```

`task fmt` applies the formatting and lint fixes that `task lint` only reports.

Pre-commit hooks run `ruff`, `mypy` and `openlore drift` on every commit. A hook that rewrites
a file fails the commit by design — re-stage and commit again.

Read `AGENTS.md` before making changes as an agent, and `CLAUDE.md` for the session contract.
