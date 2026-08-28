## Why

Phase 2 closed 2026-08-08 (v2.0: zero direct emits in CI, all four sanctioned command sources
live). The next rung is v3.0 — Projections: Twenty, Customer.io, and Snowflake consumers cut to
ledger-fed events, reconciliation sweeps live, M1 retired (ADR §6, Phase 3). Every projection
change in that phase queues behind one artifact: the Twenty workspace model itself — objects,
roles, and the `project-domain-event` apply logic that `twenty-projection` will feed.

The gate that held this change is resolved. **D4 closed 2026-08-12 (DNA-908): artifact, not
live-apply.** The catalog→Twenty metadata generator emits the serialized Metadata API operation
set as a CI-built, validated artifact; a separate deploy step applies it; the same artifact
promotes dev → staging → prod. Live-apply against a running instance is rejected. If the
community scaffolding CLI (`create-twenty-app` / `yarn twenty dev:build`) cannot emit an
equivalent artifact, the S0.2 Twenty-metadata generator lineage (`pulse_core` catalog machinery)
emits its own — this change implements that generator path as the contract surface, and the CLI
manifest evaluation rides the instance-gated wave.

One dependency is real and open: **the Twenty dev instance is not yet provisioned (DNA-909,
manual)**. This proposal is structured so that everything except live-apply verification is pure
codegen/artifact work, dispatchable now; the tasks that need a running instance are explicitly
gated on DNA-909 and sit alone in the final wave.

## What Changes

- **New package `packages/twenty-app`**: the Twenty app workspace member — TypeScript object
  definitions (Patient, Program, PatientProgram, Provider, Clinic, DomainEvent per
  `design/platform/twenty-data-model.md`, corrected by the app-scaffold notes: no base-field
  declarations, `RAW_JSON` first-class, real NOT NULL via `isNullable: false` + default), roles
  as code (producers create-only on DomainEvent; staff read-only on status fields; app role
  minimal), and the `project-domain-event` logic function with Vitest unit tests at a faked
  client boundary.
- **Catalog → Twenty metadata generator** in `pulse_core` (the S0.2 catalog-machinery lineage,
  next to `catalog_gen.py`): `state_catalog.yaml` → SELECT options arrays, the projection lookup
  table, and the **serialized Metadata API operation set** — the D4 artifact. Options arrays are
  generated into the app package, never whole files; `universalIdentifier`s live in a checked-in
  map keyed by state/object/field name and are never regenerated.
- **Artifact validation as a CI check**: schema validation of the operation set, determinism
  (byte-identical on re-run), UID-map stability, and options ⊆ catalog states — all inside
  `task check` (Python side) so a drifted artifact is a red PR, not a deploy surprise.
- **Separate deploy step** (`twenty_deploy` CLI): reads a validated artifact, applies it to a
  named target instance via the Metadata API, idempotent on re-apply, `--dry-run` prints the
  operation plan with no socket. Promotion is the same artifact file pointed at the next
  environment — the deploy step carries zero generation logic.
- **CI wiring**: `task check` grows the vitest unit suite and artifact checks behind Taskfile
  targets; `main.yml` gains only a setup-node step — every `run:` command stays exactly
  `task check` (cat4 contract). `openspec`/`openlore` stay out of `task check`, unchanged.
- **DNA-909-gated wave (cannot dispatch until the dev instance exists)**: live apply of the
  artifact to dev with schema read-back verification, live exercise of `project-domain-event`
  against the dev server, the create-twenty-app manifest-path evaluation, and the promotion
  runbook. Everything earlier runs against fixtures and golden files only.
- Synthetic data only throughout: fixtures draw on `packages/synthea-seed` shapes; no PHI in
  the artifact, fixtures, logs, or receipts — the artifact is generated from the catalog, which
  contains state vocabulary, never patient data.

## Capabilities

### New Capabilities

- `twenty-metadata-artifact`: the D4 artifact — catalog-generated SELECT options and projection
  lookup, the serialized Metadata API operation set as a CI-built deterministic artifact,
  checked-in `universalIdentifier` map (mint once, never regenerate), validation gate
  (schema, determinism, UID stability, catalog containment), and the no-live-apply rule: the
  generator never talks to an instance.
- `twenty-projection-apply`: `project-domain-event` semantics as versioned, unit-tested code —
  entity resolution via crosswalk, per-dimension LWW guard, dimension isolation, first-event
  PatientProgram creation, unresolved-ref orphan behavior, unknown-type rejection.
- `twenty-artifact-deploy`: the separate deploy step — validated-artifact-only input, named
  target instance, idempotent re-apply, dry-run plan, dev → staging → prod promotion of one
  artifact; live verification explicitly gated on the dev instance (DNA-909).

### Modified Capabilities

_None._ The catalog source/versioning/release specs are untouched: this change adds a new
consumer of `state_catalog.yaml` through the same generator seam `catalog-source` already pins
(`catalog_gen`'s load path), and emits into a new generated surface. Adding a state to the
catalog flows into the artifact by regeneration, under the existing `catalog_generated_surfaces`
serial lane.

## Sequencing note — Phase 3 is several changes; this is the first

Per the roadmap's queued-changes table, Phase 3 splits into eight changes. This proposal covers
`pulse-app-scaffold` only. The rest, with their gates, unchanged from the roadmap:
`twenty-projection` (gate: this change — the ledger-fed consumer writing DomainEvent rows,
heal-back write closing D8), `customerio-projection` and `snowflake-projection` and
`survey-engine-ingress` (gate: Phase 2 exit, the last adding PX schema validation),
`reconciliation-sweeps` (gate: `snowflake-projection`), `projection-rebuild-drill` (gate:
`twenty-projection`; carries Demo 3), and `m1-retire-patient-state` (gate: `twenty-projection`;
ADR §6.2). M1 is deliberately **not** in this change: retiring `patients.enrollment_status`
requires the projection consumer to exist, and this change only builds the model it projects
into.

## Impact

- New workspace member `packages/twenty-app` (TypeScript — the repo's first; node toolchain
  enters CI as a setup step, run commands unchanged) plus new `pulse_core` modules
  (`twenty_metadata`, `twenty_deploy`) with the established conventions (ruff, pyright, pytest,
  `--disable-socket`, coverage floor).
- Generated surfaces: options arrays and the operation-set artifact join the
  `catalog_generated_surfaces` serial lane; the UID map is checked in and hand-owned.
- No ledger, command-API, or schema changes. No new Snowflake objects. Depends on
  `pulse_core.catalog_gen`'s load path only.
- External dependency (deferred): a Twenty dev instance (DNA-909, manual provisioning, open).
  Wave 3 tasks name it as their gate; no earlier task touches a live instance. The Metadata API
  as a consumed surface is registered in `docs/contracts/consumes.md` by this change's doc task,
  pinned to the Twenty version the image pin will carry.
- PHI: none anywhere in this change — the generator input is the state catalog (vocabulary, not
  data); fixtures are synthetic (synthea-seed shapes where a patient-shaped value is needed);
  deploy receipts carry object/field names and operation counts only. The deploy CLI's error
  paths are tested to never echo response bodies that could carry workspace data.
- Rollback: pre-production, additive only — no instance exists to have applied anything to at
  merge time. Reverting is removing the package and modules; the UID map is inert until first
  apply.
