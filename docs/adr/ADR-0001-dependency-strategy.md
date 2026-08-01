# ADR-0001: Dependency strategy — consume, vendor, or build

- **Status**: Accepted
- **Date**: 2026-07-31

## Context

repo-ade composes four independent tools (OpenSpec, OpenLore, Orca, go-task) plus the Python
baseline from cookiecutter-uv. Each could plausibly be consumed as a dependency, vendored into
the repo, or reimplemented. Without a stated rule the default drifts toward reimplementation,
because writing glue is easier than reading someone else's docs — and the result is an
orchestration runtime competing with the tools it wraps.

The repo also has an unusual consumption model: it is a GitHub template, so a generated repo
receives a *copy* and never an upgrade. Anything absorbed into the template is frozen at
generation time for every downstream repo.

## Decision

We will **consume** the four tools as external dependencies, installed independently and never
vendored:

- OpenSpec and OpenLore as npm globals; Orca as a desktop app and CLI; go-task via brew.
- Python tooling from PyPI, declared in `pyproject.toml` and locked in `uv.lock`.

We will **build** only thin glue: `Taskfile.yml` targets, `scripts/dispatch_tasks.py`,
`scripts/collect_handoffs.py`, the `AGENTS.md` contract, and the `tests/scaffold/` gate suite.
Glue may translate between tools; it may not reimplement what a tool already does.

We will **vendor nothing.**

## Consequences

Easier: each tool upgrades on its own schedule; no fork to maintain; the surface we own stays
small enough to test exhaustively — the nine gates cover it.

Harder: the toolchain is a real prerequisite burden, so a contributor must install four CLIs
before anything works. `tests/scaffold/cat2_toolchain.sh` exists precisely because that
prerequisite list is load-bearing and easy to get wrong.

Foreclosed: the tools are not pinned to exact versions, so an upstream breaking change reaches us
on the next install rather than on a deliberate bump. The gates are the safety net — they fail
loudly rather than silently drifting. If that trade stops paying, the response is to pin
versions, not to vendor.

Because CI runners install neither OpenSpec nor OpenLore, any gate depending on them must stay
out of `task check`. This is enforced, not merely documented, by
`tests/scaffold/cat4_ci_contract.py`.

## Alternatives considered

**Vendor the tools** — rejected: three of the four are not Python, and vendoring an npm CLI into
a Python template means maintaining a fork of software we do not understand deeply.

**Pin exact versions of all four CLIs** — rejected for now: the tools are early and move fast, so
pinning would mean routine bump work with little safety gained over the gates. Revisit if an
upstream change breaks a generated repo.

**Build a single orchestration runtime replacing them** — rejected: this is the design the "thin
glue" principle exists to prevent. Each tool owns its layer; a runtime that wraps all four would
own none of them well, and would have to be maintained against four moving upstreams.
