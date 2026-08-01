# Publishes

What this repo exposes to other repos and teams. Anything not listed here is an implementation
detail and may change without notice.

Cross-repo integration happens through this document — a published Snowflake object, an API, or
a released package. **Never integrate by cloning another repo into this one.** A side-clone
couples you to someone else's implementation details and to their refactors.

Record each entry with enough detail that a consumer can depend on it without reading the code:

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| _e.g._ `ANALYTICS.DIM_PATIENT` | Snowflake view | stable | grain: one row per patient; PHI — access via role `ANALYST_PHI` |
| _e.g._ `GET /v1/encounters` | REST API | beta | paginated; contract in `docs/api/encounters.yaml` |

## This repo

repo-ade is a repository template. It publishes no runtime data surfaces — no Snowflake objects,
no APIs, no released package. What it publishes is a **repository shape**, consumed by
`gh repo create --template` rather than by an import:

| Surface | Kind | Stability | Notes |
|---|---|---|---|
| Repository structure | template | stable | committed tree only; see the delivery classes in `CLAUDE.md` |
| `Taskfile.yml` targets | command contract | stable | `task check` is what CI runs; thin-glue targets take `CHANGE=<name>` |
| `bootstrap.sh` interface | script | stable | `bootstrap.sh <project-name> <package-name> <description>` |
| `AGENTS.md` operating contract | convention | stable | binding on agents in Orca worktrees |

Generated repos own their copies outright. Improvements to the template do **not** flow
downstream automatically — a generated repo is a fork in fact, if not in name.
