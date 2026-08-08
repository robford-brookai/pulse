# Consumes

What this repo reads from elsewhere. Each entry should link the publisher's `publishes.md` so a
breaking change upstream is traceable to the consumers it affects.

**Never satisfy a dependency by cloning the producing repo into this one.** Consume a published
surface — a Snowflake object, an API, or a released package.

| Dependency | Kind | Publisher contract | Breakage risk |
|---|---|---|---|
| _e.g._ `RAW.ZCC_CONTACTS` | Snowflake table | `zcc-ingest/docs/contracts/publishes.md` | schema drift on upstream vendor change |

## This repo

### Verdict mart (dbt, Snowflake)

`packages/verdict-relay` reads the verdict mart the dbt project computes in Snowflake and declares
each row to the ledger as a `declare_verdict` command
(`openspec/changes/s12-verdict-relay/specs/verdict-mart-read/spec.md`). Per roadmap P5
(`design/delivery/pulse-program-roadmap.md`), this relay supersedes the clinic-rules-engine
Snowpark emitter as the verdict write path — see the supersession note in
`design/platform/clinic-rules-engine.md`.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| Verdict mart | dbt-computed Snowflake table(s) | fixture-pinned contract: one row per `(subject_id, verdict_type, run)`, columns `subject_id, verdict_type, outcome, reason, rule_version, as_of, lineage_ref, computed_at` | a row missing a contract column or carrying an unparseable `as_of`/`computed_at` fails the run before any declaration, naming the offending row; the dbt side has no publisher contract of its own yet — this repo's fixtures are the only pinned shape |

The relay pages on `computed_at` and persists its cursor through the ledger's writer-state
facility (`pulse_core.cursor`), scoped to its own writer id — so schema drift on the mart is caught
at read time, never silently skipped by resuming past a bad page.

### Event transport (runtime)

With the Kafka → EventBridge migration
([ADR-0002](../adr/ADR-0002-ocean-absorption-and-eventbridge-transport.md)), the absorbed OCEAN
services in `packages/ocean` consume AWS messaging primitives instead of a broker:

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| EventBridge `ocean` bus | AWS managed bus | `boto3` / `aiobotocore`; bus name via `OCEAN_EVENT_BUS_NAME` | PutEvents entry cap (256 KB) rejects oversized envelopes; missing bus name would route to the account `default` bus, so it is never left unset |
| SQS consumer queues | AWS managed queues | one queue per consumer, URL via `SQS_QUEUE_URL` | standard queues do not preserve order — order-dependent consumers carry a sequence guard keyed on the envelope key |
| LocalStack | local dev container | `packages/ocean/infra/docker-compose.yml` | local-only stand-in for the two rows above; provides bus, rules, queues, DLQs |
| Postgres `failed_webhooks` | table (publish DLQ fallback) | ocean's own Postgres | a publisher constructed without a `db_session_maker` logs failures without durably queuing them |

`confluent-kafka` and the Redpanda containers are removed. None of these is reached by
`task check` — no live network in tests; the LocalStack stack exists for local simulation runs.

### Twenty comment API (`twenty-kanban-webhook-ingress`, DNA-878)

`pulse_ledger.twenty.client` posts a rejection comment back to the Twenty card via Twenty's REST
API — the one outbound surface the D8 kanban route introduces (comment-create only, no other
verb). The shape is a documented guess, not a live-verified contract: no live Twenty instance
exists before Phase 3, so every test runs against recorded/synthetic responses at the HTTP
boundary, `--disable-socket`. **This dependency's exact request/response shape is re-verified
against a live Twenty instance in Phase 3, before production enablement** — a shape drift there
changes this module's URL/body construction and its recorded fixtures, nothing else (design.md
Open Questions).

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| `POST /rest/comments` | REST API (pinned, not live-verified) | Twenty; bearer token via `PULSE_LEDGER_TWENTY_API_TOKEN` | comment shape drift surfaces only at the Phase 3 live re-verification; until then, fixtures are the only pinned contract, same posture as the verdict mart row above |

### Producer-policy gate (`producer-ingress-policy`, DNA-885–DNA-888)

`tests/test_producer_ingress_policy.py` classifies `packages/ocean` producer source against the
state catalog contract published in the "State catalog" entry of `publishes.md`. The gate reads
exactly the pinned surfaces — nothing else: not the retired Appendix C seed, not the Snowflake
`catalog` schema rows, not `catalog_gen`/`catalog_release` internals. Policy and procedure are
documented at `packages/ocean/docs/producer-policy.md`.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| `catalog/state_catalog.yaml` | versioned YAML file, repo head | this repo, `catalog-authority` | a catalog release narrowing or removing a state can turn an existing ocean vocabulary red — intended per §4.4, the failure names the exact collision |
| `pulse_core.generated` (`TRANSITIONS`) | workspace package surface | this repo, `catalog-authority` | the classifier takes `transitions` as an injectable argument, defaulting to this surface; a signature change to `TRANSITIONS` breaks the gate at import time, not silently |

### Toolchain

pulse consumes four external tools, inherited from the repo-ade template. None is vendored; each
is installed independently and pinned only where a gate depends on its behaviour.

| Dependency | Kind | Source | Breakage risk |
|---|---|---|---|
| OpenSpec | npm global CLI | `@fission-ai/openspec` | change lifecycle commands; `spec:archive` gate |
| OpenLore | npm global CLI + MCP server | `openlore` | `openlore drift` is a pre-commit hook; `orient()` for agents |
| Orca ADE | desktop app + CLI | onorca.dev | worktree execution; `dispatch_tasks.py` prints its commands |
| go-task | task runner | brew / taskfile.dev | every documented command; CI invokes `task check` |
| Linear CLI | CLI, **optional** | linear.app | only `workflow:lint:linear`; absent means that check skips, never fails |
| Linear GraphQL API | HTTPS API, **optional** | `api.linear.app/graphql` via `LINEAR_API_KEY` | only `linear:sync`; absent means it plans without mutating |

Both Linear entries are optional, and neither is ever reached by `task check`.

`workflow:lint:linear` verifies WORKFLOW.md's declared team, project and status set against the
live workspace, printing `SKIPPED` and exiting 0 when the client is missing. A gate that fails
because a machine lacks an optional tool teaches people to ignore it; one that answers and
disagrees is a hard failure.

`linear:sync` talks to the GraphQL API directly over stdlib `urllib` — deliberately no HTTP
dependency, so the workspace lockfile stays untouched. Without `LINEAR_API_KEY` it prints the plan
it would apply and exits 0; `APPLY=1` without a key is an error rather than a silent no-op.

Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`; that lockfile, not
this table, is the source of truth for them.

Because OpenSpec and OpenLore are npm globals that CI runners do not install, they must stay out
of `task check`. `tests/scaffold/cat4_ci_contract.py` enforces this.
