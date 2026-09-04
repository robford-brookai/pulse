# pulse

Patient unified ledger of state and events.

This repo holds PULSE, Brook's system of record for patient care state: the ledger, the command
API that writes to it, the state catalog that defines what's legal to write, and the projections
that read it back for other systems. It also carries the design docs the platform is built from
(`design/`) and the agent development environment (ADE) scaffold that runs this repo's own
change lifecycle.

## Why PULSE exists

Ask three Brook systems whether a patient is actively enrolled and you can get three answers,
because each one re-derives that answer from its own copy of history. That is how billing
disputes, stale dashboards, and disagreements between a report and a screen happen.

PULSE fixes this by giving every Brook system one place to declare facts and one place to read
the answer, instead of each keeping its own copy. Every declared fact goes into one append-only
journal — nothing is ever edited or deleted, a mistake gets corrected by a new entry that
reverses the old one — and one current-state row per tracked subject (an enrollment, a referral,
a billing episode) updates in the same transaction as the journal entry that changed it. It's
the bank statement and balance pattern: the statement never changes, and the balance is always
whatever the statement says right now.

## Status

Phases 0 through 2 are complete and shipped as v2.0 on 2026-08-08. Phase 3 (projections) is
active. Twenty-two changes have been archived, most recently `connector-pattern` (the shared
connector kit) and `pulse-demo-closeout` (the end-to-end demonstration and the projection
rebuild drill), both on 2026-09-02. `billing-connector` is the change currently in flight.

- Program status: [`.planning/reports/2026-08-30-program-status.md`](.planning/reports/2026-08-30-program-status.md)
- Roadmap and phase table: [`design/delivery/pulse-program-roadmap.md`](design/delivery/pulse-program-roadmap.md)

## How PULSE works

PULSE keeps one system of record for what happened to a patient, a referral, a billing episode,
and the other subjects it tracks. Every fact enters through one door, gets checked against one
rulebook, and lands in one place before anything downstream sees it. Five parts do that work.

| Part | What it is | What it guarantees |
|---|---|---|
| State catalog | A versioned file (`catalog/state_catalog.yaml`, generated into `pulse_core.generated`) listing every subject's legal states and transitions | No transition reaches the ledger unless the catalog says it's legal |
| Ledger | An append-only Postgres schema (`ledger`), written by one service (`packages/pulse-ledger`) | Every event is bitemporal and immutable — corrections are reversals, never edits ([`openspec/specs/ledger-record/spec.md`](openspec/specs/ledger-record/spec.md)) |
| Command API | The one HTTP write path into the ledger | Every write is validated against the catalog, idempotent by client-supplied key, and attributed to the authenticated writer ([`openspec/specs/command-api/spec.md`](openspec/specs/command-api/spec.md)) |
| Event bus | An EventBridge relay fed from the ledger's transactional outbox | Every committed event reaches subscribers at least once, in a per-subject sequence |
| Projections | Read models built by consuming the bus (Twenty, Snowflake, and others) | Never write back — they reflect the ledger, they don't define it |

The catalog is generated, not hand-maintained: a PR against `catalog/state_catalog.yaml` regenerates the
transition tables the command API validates against, so legality changes without a code deploy.
The ledger tags every event with an evidence class (direct, corroborated, inferred, interpolated,
or genesis) and an epoch (declared forward or reconstructed backfill), so history stays
distinguishable by how well it's known, not just what it says.

Two properties hold across all five parts, and they're the reason you can trust what the ledger
says without re-checking it downstream.

### Idempotency

Every command carries a client-supplied idempotency key, derived from the writer, the command
type, the payload, and a logical timestamp. Submit the same fact twice — a retry after a dropped
response, a redelivered queue message, a connector that reruns a batch — and the command API
returns the original commit's event ID, marked as a replay. It never creates a second event.

This is what makes retries safe by default. A writer that isn't sure whether its last call landed
doesn't need to check first. It just calls again with the same key, and the ledger sorts out
whether that's a new fact or the same one arriving twice.

### Attribution

Every ledger event names the writer that declared it, and that name comes from the authenticated
credential, never from the request body. A command body can't carry an `actor_type`, `actor_id`,
`actor_authority`, or `producer` field at all — if it does, the command API rejects the whole
command rather than silently overwriting the claimed value with the real one.

That's a deliberate choice, not an oversight. Silently correcting a spoofed actor would make a
misconfigured writer look correct forever: the ledger would record the right value, and the writer
would never learn its credential setup was wrong. Rejecting it is the only behavior a writer can
actually notice.

### One fact's path

Say a clinic system verifies a patient's coverage and the enrollment should move to `active`. The
fact travels through all five parts before anything reads it as true.

1. A producer — a connector, a service, an internal job — sends `declare_transition` to the command API, authenticated with its own credential, carrying an idempotency key and the coded reason for the transition.
2. The command API validates the transition against the state catalog's adjacency for the subject's current state. An illegal transition (say, `active` from a state that can't legally reach it) is rejected with the catalog reason — nothing is written.
3. A legal transition commits: the event row and the subject's new current-state row land in the same Postgres transaction, so no reader ever sees one without the other.
4. The commit also writes to the ledger's transactional outbox, which the EventBridge relay drains onto the bus.
5. Projections consuming the bus — Twenty, Snowflake, whatever else subscribes — update their own read models. None of them can write back to the ledger.

If step 1 gets retried — the connector times out waiting for a response and resends — the
idempotency key from that first attempt makes step 3 a no-op: the command API returns the event ID
already committed instead of writing a second one.

### Connectors

Every external system — an EHR feed, a partner API, a legacy Mongo export — reaches PULSE through
a connector package built on the shared kit in
[`pulse_core.connector`](packages/pulse-core/src/pulse_core/connector/). The kit provides the
inbound read contract (a row source with per-row validation and a durable cursor), the declare
pipeline (idempotency-key derivation and receipt classification), and the outbound consume loop
(queue dedupe and watermarked write-backs). A malformed row fails by naming its position and
column, never by logging the value in it.

A connector holds exactly one writer credential of its own, plus a credential for the target
system if it writes back, and never holds a connection to the ledger database. It only ever talks
to the command API and the bus — the same door and the same rulebook as every other producer,
whether that producer is a connector, an internal service, or a scheduled job.

## What's in this repository

### Packages

Fourteen packages live under `packages/`. Twelve are Python (`pyproject.toml` workspace
members); `twenty-app` and `twenty-model` are TypeScript, this repo's only non-Python packages.

**Core and service**

| Package | What it does |
| --- | --- |
| [`packages/pulse-core`](packages/pulse-core) | Client SDK for the ledger: command submission, response classification, the consume convention. |
| [`packages/pulse-ledger`](packages/pulse-ledger) | The ledger service itself: command API, ledger schema, outbox relay. |

**Producers and connectors** — packages that declare commands onto the ledger's single write path

| Package | What it does |
| --- | --- |
| [`packages/verdict-relay`](packages/verdict-relay) | Reads the warehouse verdict mart and declares verdicts on the ledger. |
| [`packages/consent-ingress`](packages/consent-ingress) | Turns delivered Customer.io consent data (`streamline.cio_raw`/`cio_prod`) into `record_communication_consent` commands. |
| [`packages/billing`](packages/billing) | Billing engine: event-driven eligibility and coverage rule evaluation, with its own Postgres store (`billing_engine` schema). |
| [`packages/billing-connector`](packages/billing-connector) | Turns the billing engine's folded facts into attributed, versioned billing verdicts on the ledger. |
| [`packages/schedules`](packages/schedules) | Clock-driven schedulers: month-open BillingEpisode declaration and the D9 consent reconciliation sweep. |
| [`packages/identity`](packages/identity) | TIDE matcher v1: deterministic identity resolution for the received-to-resolved Referral transition. |

**Projections and the Twenty surface** — Twenty is the CRM-style board UI this repo projects ledger state onto

| Package | What it does |
| --- | --- |
| [`packages/twenty-projection`](packages/twenty-projection) | Ledger-fed board projection: committed ledger events upsert Twenty records via its REST API, ordered by `(subject_id, ledger_seq)`. |
| [`packages/twenty-app`](packages/twenty-app) | The PULSE views, navigation, and projection logic as TypeScript, run against a stock Twenty server (no fork). |
| [`packages/twenty-model`](packages/twenty-model) | The artifact-owned half of the Twenty model: six objects and three roles, compiled to `packages/twenty-app/artifact/operations.json` and applied to a workspace by `task twenty:deploy`. |

**Supporting**

| Package | What it does |
| --- | --- |
| [`packages/synthea-seed`](packages/synthea-seed) | Deterministic synthetic population: a pinned Synthea generation receipted by checksum manifest, with declarative Brook fixture overlays. |
| [`packages/archaeology`](packages/archaeology) | The single read-only access seam to the legacy Mongo cluster, used for backfill discovery and later bulk extraction. |
| [`packages/ocean`](packages/ocean) | The absorbed legacy service tree — the prior system PULSE is replacing, kept in-repo during migration. |

### Documentation: `design/` vs `docs/`

Two doc trees, split by concern.

`design/` is what is being built:

- `design/platform/` — target architecture: event envelope, state catalog, Snowflake landing, the Twenty data model, the app scaffold, the clinic rules engine.
- `design/migration/` — the legacy-to-PULSE path: RPC object-model assessment, ledger backfill plan, Mongo archaeology, ocean absorption, genesis and cutover.
- `design/delivery/` — program execution: work orders, runtime readiness.

`docs/` is how this repo runs:

- `docs/adr/` — architecture decision records, append-only, one file per decision.
- `docs/contracts/` — what this repo publishes and consumes across repo boundaries, plus the billing boundary and producer registry.
- `docs/runbooks/` — operational procedures, one file per surface (billing, consent sweep, Twenty deploy, verdict relay, and more).
- `docs/process/` — how the agent development environment workflow itself operates, including the work-order dispatch template.
- `docs/architecture/`, `docs/ci-lessons.md`, `docs/mcp-servers.md` — the rendered architecture site and residual lessons no automated gate can express.

### Other top-level directories

- `openspec/` — the change lifecycle: proposals, designs, specs, and tasks. `openspec/specs/` is the accumulated behavioral baseline, currently around 49 capability specs, written only by archiving a completed change.
- `tests/scaffold/` — gates that validate this repo's own structure and wiring (nine categories, `cat1` through `cat9`), not the packages themselves.
- `scripts/` — the glue between OpenSpec, Orca, and go-task: task dispatch, handoff collection, Linear sync, and per-package demo scripts.
- `work_orders/` — one file per task, emitted by `task dispatch` from an OpenSpec change's `tasks.md`. Generated, not tracked.
- `handoffs/` — the collected `HANDOFF.md` receipts from completed change waves, one directory per change.
- `.planning/` — ad-hoc reports and work-order tracking that fall outside the trees above.

## Running and verifying it

### Quickstart

```bash
task install
task check
```

`task install` runs `uv sync --all-packages`, setting up the virtual environment and every
workspace package. `task check` runs the same gates continuous integration (CI) runs: lint,
typecheck, tests, the Twenty app suite, and a docs build. Run `task` on its own to list every
command, grouped by area, in the order you reach them as you work. `task check` needs no Java —
Java (17+) is a prerequisite only of `task synthea:regen PROFILE=<p>`, the deterministic
synthetic-population regeneration in `packages/synthea-seed`, which shells out to a
checksum-pinned Synthea JAR and verifies the output against a committed manifest. A local
divergence names the files in its diff; `REPIN=1` re-pins as a reviewed change.

### Task areas

`Taskfile.yml` groups every command under a numbered area comment, in the order you reach them:

- **Environment** — `task install`, plus `task mcp:check` for MCP diagnostics.
- **Develop** — `task fmt` to auto-format, `task lint` to check without changing anything,
  `task typecheck`.
- **Test** — `task test` (coverage-gated), `task test:all` (adds the slow scaffold gates).
- **Demo** and **Gate** — the five demonstrations and the `task check` / `task verify` gates,
  both covered below.
- **Docs** — `task docs` (serve MkDocs locally), `task docs:build` (build strictly).
- **Spec lifecycle, drift and memory** — OpenSpec (`task spec:validate`) and OpenLore
  (`task lore:drift`) behind the change lifecycle.
- **Work distribution, template updates** — dispatches OpenSpec tasks to Orca worktrees
  (`task dispatch`, `task collect`) and pulls template fixes down (`task template:sync`).

### The demos

Five scripts under `scripts/demo/` each walk a slice of the system end to end and exit nonzero
on the first failed assertion. None run inside `task check` — offline demos need Docker, live
demos need dev credentials — but each has a smoke-parse test so `task check` still catches an
import-breaking change:

| Demo | Proves | Offline or live | Task target |
|---|---|---|---|
| 1 | Ledger commit, replay, and fold round trip | Offline (LocalStack + Postgres) | `task demo:1` |
| 2 | Identity resolution, then the signed kanban drag ingress | Offline (fixtures only) | `task demo:2` |
| 3 | Live kanban drag against dev Twenty | Live (dev) | `task demo:3` |
| 4 | Live billing declare-back against the dev mart | Live (dev) | `task demo:4` |
| 5 | One synthetic patient, six stages, end to end | Both | `task demo:e2e` / `task stage:e2e:live` |

Demo 5 is the one to run first. It walks a single synthetic patient through all six seams PULSE
owns, in order, each stage asserting its outcome before the next begins: identity resolution,
consent ingress, a signed board drag, a billing verdict declared from the mart, cross-window
agreement between the board, warehouse, and ledger fold, and a projection rebuild drill.
`task demo:e2e` runs it offline against Docker and LocalStack. `task stage:e2e:live` stages the
environment (scratch credentials, derived Snowflake variables, a preflight check) and then runs
the identical assertions against the development environment. Full detail, every live
credential, and how to resume a stopped walk: `docs/runbooks/demo5-end-to-end.md`.

### Testing and the gates

`task check` is the contract between your laptop and CI: `.github/workflows/main.yml` runs
exactly this target, so green locally means green in CI. It covers lint, typecheck, the full
test suite with coverage, Twenty artifact validation, the Twenty app's own test suite, workflow
linting, and a strict docs build. No test here touches a live network or live credentials — the
live-only paths (`demo:3`, `demo:4`, `demo:e2e:live`, every `deploy` target) are excluded by
design and run attended, by a human, outside a worktree.

`tests/scaffold/` validates the repo's own structure, not the `pkg_pulse` package: nine
categories covering directory structure, toolchain, config validity, the CI command contract,
glue-script logic, edge cases, git hooks, docs consistency, and a golden end-to-end workflow
run. They encode real past failures, so `Taskfile.yml`, a GitHub workflow, or `bootstrap.sh` is
what's most likely to break one.

`task verify CHANGE=<id>` extends `task check` with two checks CI's runners can't do: `openlore
drift` for spec/code drift, and `openspec validate` for the named change. Run it before
archiving a change, `task check` for everything else.

## How work happens here

This repo is an agent development environment (ADE): agents plan, implement, and ship changes
through a defined lifecycle, with a human reviewing and merging. There is no orchestration
framework holding it together. Four tools each own one layer, and a handful of scripts plus
`AGENTS.md` glue them into a single flow.

| Tool | Owns |
|---|---|
| OpenSpec (`openspec/`) | Change lifecycle — proposal, design, specs, tasks, archive |
| OpenLore (`.openlore/`) | Call graph and drift detection, exposed to agents via `orient()` |
| Orca | Isolated git worktrees, one per task, for parallel agent execution |
| go-task (`Taskfile.yml`) | Every command you run — `task check`, `task dispatch`, `task verify`, and the rest |

### The change lifecycle

A change moves through **propose → validate → dispatch → execute → collect → doc_update → verify
→ merge → archive**. `WORKFLOW.md` is the operating workflow for this cycle, and its YAML block
is the source of truth — the prose and diagram in that file are checked against it, not the other
way around. Read `WORKFLOW.md` before touching dispatch behavior; this section only orients you.

In short: OpenSpec scaffolds the change and its tasks, a validation gate checks the plan before
anything dispatches, each task runs in its own Orca worktree with tests written first, and a
verify gate runs lint, tests, drift detection, and spec validation before anything merges. Work
reaches `main` by pull request, reviewed by a human — that review is the only manual step in the
cycle.

Not every task fits that path. A task whose effect no git diff can capture — reading or mutating
a live system, a force-push, repo administration — never enters a worktree. It's tracked instead
as a GitHub issue on this repo: whatever it needs that *is* reviewable (a runbook, scripts,
committed artifacts) merges by an ordinary pull request, and the attended run happens after that
PR merges, with its receipts landing on the issue.

### Cross-repo integration

Everything this repo publishes or consumes goes through `docs/contracts/publishes.md` and
`docs/contracts/consumes.md` — never by cloning another repo in here. If you need something from
another team's system, look for it as a row in `consumes.md` first; if you're exposing something
new, it belongs in `publishes.md` before anyone outside this repo can depend on it.

Two more contract documents narrow specific boundaries:

- `docs/contracts/producer-registry.md` — the authoritative list of every system that declares
  into this repo's ledger or consumes what it publishes, with direction, credential, and status
  for each. A system crossing the boundary without a row here is a defect, not a variant.
- `docs/contracts/billing-boundary.md` — states plainly that this repo prices nothing. It records
  that a billing episode qualified and which rule version decided it; every rate, code, and
  dollar amount lives in a system outside this repo.

### Data posture

No protected health information (PHI) in logs, commits, test fixtures, error messages, or
documentation — synthetic data only, everywhere. Tests run with no live network, and continuous
integration carries no secrets by default.

## Template

This repo was generated from [repo-ade](https://github.com/robford-brookai/repo-ade). Template
fixes come down with `task template:diff` and `task template:sync`; both leave `README.md`,
`CLAUDE.md`, and `src/` alone.
