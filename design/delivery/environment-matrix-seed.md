# Environment Matrix — proposal seed

**Status:** Seed, not a proposal · 2026-09-08 · **Source decision:**
`design/delivery/pulse-runtime-readiness.md` §2.1–§2.3 · **Inherits:** the shipped dev-only
posture in `packages/pulse-ledger/infra/duplo/*.json` and `packages/billing-connector/infra/duplo/*.json`

---

## 0. TL;DR

`pulse-runtime-readiness.md` §2.1 names a three-tier matrix — dev, staging, prod — and pins what
each tier holds. Only dev exists today, and it is hardcoded to the `dev01` tenant. This document
is the durable carrier for what a `environment-matrix` change must build to stand up the staging
tier: parameterizing the Duplo service definitions by tenant, standing up a staging Twenty
instance, and wiring a staging loader to the 50k-patient Synthea artifact. It records no new
decisions — §2.1–§2.3 already decided the target shape; this seed maps that shape onto what
exists and what is missing. Writing the proposal is a later act.

---

## 1. Why this exists

The roadmap's "Runtime and ops" table gates Demo 3's staging leg and cutover P0 on
`environment-matrix`, and Phase 3 itself gates on "Twenty dev instance from `environment-matrix`"
(`pulse-program-roadmap.md`). Neither gate can close on today's infrastructure: every Duplo
service definition in the repo names the `dev01` tenant literally, and a repo-wide search finds
zero `staging` references under any `packages/*/infra/` tree. The target matrix has been on
record since `pulse-runtime-readiness.md` shipped; nobody has yet written down the gap between
that target and what is deployed, or the tasks that close it. This seed does that.

---

## 2. Target matrix (`pulse-runtime-readiness.md` §2.1–§2.3)

| | dev | staging | prod |
|---|---|---|---|
| PULSE ledger | Per-developer schema in a shared Snowflake Postgres dev instance | One shared instance, prod-shaped | Production instance |
| Twenty | One shared dev instance | One instance, metadata identical to prod | Production instance |
| Data | Synthea, small seed (~500 patients) | Synthea, prod-scale shape (~50k patients), refreshed per release | PHI. Genesis-loaded per the cutover plan |
| Catalog version | Any tagged version | The release candidate version | The released version only |
| Datadog | Traces only | Full monitor set, alarms muted to Slack | Full monitor set, paging |

**§2.2 — Synthea as a versioned artifact.** `packages/synthea-seed` pins the Synthea version,
module config, and RNG seed, and emits the same population byte-for-byte on every run;
Brook-specific fixture overlays sit on top of the generated base. The staging tier's ~50k-patient
population is this artifact, not a hand-curated set.

**§2.3 — Promotion path.** Catalog release → generated surfaces build in CI → deploy to staging →
staging smoke suite (command round-trips per state machine, kanban heal-back, projection
freshness probe) → tagged promotion to prod. The same artifact promotes; nothing regenerates
between staging and prod.

---

## 3. What exists today

Dev only, and hardcoded to one tenant:

- `packages/pulse-ledger/infra/duplo/command-api.service.json`, `command-api.lb.json`, and
  `relay.service.json` — all target tenant `dev01-brook` (e.g. `relay.service.json` addresses
  `duploservices-dev01-brook-ocean` literally).
- `packages/billing-connector/infra/duplo/billing-connector.service.json` — same posture: its
  queue URL and the `pulse-ledger-api` host it calls both name `duploservices-dev01-brook`
  literally.
- No `packages/*/infra/` tree contains a `staging` reference of any kind — grepped repo-wide,
  zero hits.
- Twenty: one shared dev instance only (`twenty-dev-instance`, DNA-1019); no staging Twenty
  instance exists.
- `packages/synthea-seed` generates the small dev-scale population; the ~50k prod-scale artifact
  the staging tier needs is produced by the `Synthea regen` workflow
  (`.github/workflows/synthea-regen.yml`), which exists but is not yet consumed by any staging
  loader.

---

## 4. The work

Not yet broken into numbered tasks with dependencies and models — that is the proposal's job.
The shape of what closes the gap:

- **Parameterize the Duplo service JSON by tenant.** The `dev01-brook` literal in
  `command-api.service.json`, `command-api.lb.json`, `relay.service.json`, and
  `billing-connector.service.json` becomes a substituted value (the existing
  `__BILLING_CONNECTOR_IMAGE__`-style placeholder-and-substitute pattern already used for image
  tags is the precedent — apply the same mechanism to the tenant name), not a second hardcoded
  copy per environment.
- **A staging tenant for `pulse-ledger-api`, the relay, and warehouse-sync.** Three services
  currently addressed only under `dev01-brook` need a staging-tenant deployment following the
  same shapes.
- **A staging Twenty instance, metadata identical to dev.** Per §2.1's matrix row — same
  Metadata API artifact promotes (D4's build ≠ publish split, `docs/contracts/consumes.md`), just
  applied to a new target.
- **A staging loader consuming the 50k Synthea artifact.** Wires the `Synthea regen` workflow's
  output (`.github/workflows/synthea-regen.yml`) into a load step against the staging ledger and
  Twenty instances — the piece the workflow's own header comment names as not yet built
  ("the artifact is what the staging loader (environment-matrix, later) consumes").
- **The §2.3 promotion path**, wired end to end: catalog release → CI build → staging deploy →
  staging smoke suite → tagged promotion to prod, with the smoke suite covering command
  round-trips per state machine, kanban heal-back, and a projection freshness probe.

---

## 5. Entry gates

Two things must clear before this change is proposed.

### Gate 1 — Synthea regen workflow green

The `Synthea regen` workflow (`.github/workflows/synthea-regen.yml`) has failed its last five
scheduled runs (2026-08-10 through 2026-09-07). A fix is in flight as of 2026-09-08. The staging
loader this seed describes consumes that workflow's artifact directly, so a red regen job is a
red input to the loader it would otherwise be exercising in CI.

Clears when the workflow runs green on `main`.

### Gate 2 — a Phase 3 change slot free

Practice on this program keeps at most two changes in flight at once, deliberately
(`openspec/changes/billing-connector/design.md` decision 9, Rob's call 2026-09-02) — serial-lane
tasks across two simultaneously-dispatched changes collide on shared files
(`Taskfile.yml`, workspace `pyproject.toml`), so the coordinator checks before releasing a wave
in one against a wave in the other. `environment-matrix` is Phase 3 runtime-and-ops work; it
needs one of those two slots open when it is proposed.

Clears when a slot opens.

---

## 6. Linear home

`task linear:sync` targets **PULSE / Declared-State Funnel**, where every runtime-and-ops change
in this repo (`pulse-spcs-deployment`, `d14-spcs-latency-spike`) has landed. No reason to deviate
here.
