# Consumes

What this repo reads from elsewhere. Each entry should link the publisher's `publishes.md` so a
breaking change upstream is traceable to the consumers it affects.

**Never satisfy a dependency by cloning the producing repo into this one.** Consume a published
surface — a Snowflake object, an API, or a released package.

| Dependency | Kind | Publisher contract | Breakage risk |
|---|---|---|---|
| _e.g._ `RAW.ZCC_CONTACTS` | Snowflake table | `zcc-ingest/docs/contracts/publishes.md` | schema drift on upstream vendor change |

## This repo

repo-ade consumes four external tools. None is vendored; each is installed independently and
pinned only where a gate depends on its behaviour.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| OpenSpec | npm global CLI | `@fission-ai/openspec` | change lifecycle commands; `spec:archive` gate |
| OpenLore | npm global CLI + MCP server | `openlore` | `openlore drift` is a pre-commit hook; `orient()` for agents |
| Orca ADE | desktop app + CLI | onorca.dev | worktree execution; `dispatch_tasks.py` prints its commands |
| go-task | task runner | brew / taskfile.dev | every documented command; CI invokes `task check` |

Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`; that lockfile, not
this table, is the source of truth for them.

Because OpenSpec and OpenLore are npm globals that CI runners do not install, they must stay out
of `task check`. `tests/scaffold/cat4_ci_contract.py` enforces this.
