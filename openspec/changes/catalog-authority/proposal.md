# Proposal — catalog-authority

## Why

The generated command surface — the transition tables and Pydantic command types every producer
and the write-path validator import — still derives from the Appendix C seed
(`packages/pulse-core/src/pulse_core/catalog/state_catalog_seed.yaml`, `catalog_version:
appendix-c-v0.7`), which exists under an explicit retirement clause: it retires the day the
authoritative `state_catalog.yaml` lands. D18 closed 2026-08-06 (ADR-0004): the catalog's system
of record is Snowflake, edits stay in git, approval is the git PR flow, and merge to main triggers
the release job that writes immutable `catalog_version` rows — with a breaking-change rule for
releases that remove a state, narrow a ValueSet, or change a transition's legality. Nothing
implements any of that yet, and `producer-ingress-policy` (the ADR §4.4 CI gate) is gated on this
change for the catalog artifact it checks producers against.

## What Changes

- **Authoritative `catalog/state_catalog.yaml`** at the repo root, `catalog_version: 1.0.0` —
  schema-validated (subjects, commands, reason ValueSets, program config), content carried over
  from the Appendix C seed so the generated surface is behavior-identical at cutover.
- **Generator cutover**: `pulse_core.catalog_gen` reads the authoritative file; the seed file is
  deleted per its retirement clause; `pulse_core.generated` regenerates byte-identically except
  for the version pin. The existing committed-module drift test keeps gating regeneration in
  `task check`.
- **Immutable release snapshots**: every released version is frozen as
  `catalog/releases/v<version>.yaml` with a checksum manifest; `task check` verifies the head
  catalog equals its current snapshot and that no past snapshot has been rewritten.
- **Breaking-change rule (D18, runtime-readiness §4.3 verbatim)**: a release that removes a
  state, narrows a ValueSet, or changes a transition's legality is breaking. Breaking releases
  require a major version bump and a migration note with a consumer checklist (Twenty metadata
  redeploy, ConceptMap regeneration, rule_version bump if verdict criteria reference the changed
  codes) in the release PR — enforced offline in `task check` by diffing the two most recent
  snapshots.
- **D18 Snowflake release job**: a renderer (`pulse_core.catalog_release`) emits the versioned
  rows for a `catalog` schema (states, transitions, reason ValueSets, program config, plus a
  version row) — INSERT-only, tagged with the immutable `catalog_version`, Snowflake object tags
  applied, an immutability guard that no-ops an identical re-release and hard-fails a conflicting
  one. A `task catalog:release` target (plan-only without credentials, `APPLY=1` to execute, per
  the `linear:sync` posture) and a `catalog-release.yml` workflow triggered by merge to main are
  the deploy artifact. **`task check` never reaches Snowflake** — the job needs credentials CI
  does not have, so it lives outside the check contract per `docs/contracts/consumes.md`.
- **Contract for `producer-ingress-policy` (pinned here, consumed there)**: the authoritative
  catalog is `catalog/state_catalog.yaml` at the repo head; its version is the semver
  `catalog_version` field (MAJOR increments exactly on breaking releases); the programmatic
  surface is `pulse_core.generated` (`CATALOG_VERSION`, `SUBJECT_TYPES`, `TRANSITIONS`,
  `COMMAND_TYPES`). The successor's CI gate reads these and nothing else.

## Capabilities

### New Capabilities

- `catalog-source`: the authoritative catalog file — its schema, its role as the single source
  the generator reads, and the retirement of the Appendix C seed.
- `catalog-versioning`: immutable release snapshots, the breaking-change classification (state
  removed, ValueSet narrowed, transition legality changed), and the migration-note + consumer
  checklist ceremony enforced in `task check`.
- `catalog-release`: the D18 Snowflake release job — versioned, tagged, INSERT-only rows in the
  `catalog` schema; the immutability guard; and the credential-free-CI posture that keeps the job
  a deploy artifact rather than a check step.

### Modified Capabilities

_None. `command-api` already requires "Command types are generated from the catalog" — that
requirement's behavior is unchanged; only the generator's input file moves, which is
implementation. No baseline spec's requirements change._

## Impact

- New top-level `catalog/` tree (authoritative file, release snapshots, checksum manifest,
  migration notes); the seed file under `packages/pulse-core` is deleted.
- `pulse_core.catalog_gen` input path and schema models extended (valuesets, programs, semver
  version); `pulse_core/generated/__init__.py` regenerates — behavior-identical, version pin
  changes to `1.0.0`. Any task that regenerates the module releases alone on the
  `catalog_generated_surfaces` serial lane (one generated contract; producers and the validator
  both derive from it).
- New `pulse_core.catalog_release` module, `task catalog:release` target,
  `.github/workflows/catalog-release.yml` (must satisfy the cat4 CI contract — its `run:` steps
  resolve to Taskfile targets). Enabling the workflow's Snowflake credentials is a deploy step
  outside this change.
- Docs: `docs/contracts/publishes.md` gains the catalog as a published surface (file path +
  version convention + Snowflake `catalog` schema); `design/platform/state-catalog.md`
  supersession note updated (the "until `catalog-authority` lands" clause resolves);
  `docs/runbooks/catalog-release.md`.
- No PHI anywhere in this change: the catalog is states, transitions, ValueSets, and program
  config — no patient data, and the release job must never carry any.
- No live network in tests: the Snowflake side is exercised against rendered SQL and a faked
  execution boundary; `--disable-socket` posture holds.
- Rollback: pre-production and additive — reverting removes the `catalog/` tree, restores the
  seed, and re-points the generator; the Snowflake schema is empty until a deploy applies the
  job, and its rows are versioned inserts that a rollback simply stops adding to.
