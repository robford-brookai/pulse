# Proposal — synthea-seed

## Why

Every lower-tier environment and every genesis/backfill rehearsal depends on synthetic data that
is generated, not hand-curated — and deterministic, so a re-run is a diff, not a new world.
Runtime readiness §2.2 defines exactly this (`synthea-seed` as a versioned artifact), the object
model names mandatory regression fixtures that must exist as engineered patients, and the
genesis rehearsal demo needs contradictory-source fixtures to populate the quarantine queue. It
is gate-free today and unblocks staging, genesis testing, and Demo 1's richer scenarios.

## What Changes

- New workspace package `packages/synthea-seed`: pins the Synthea version, module configuration,
  and RNG seed so every generation emits the same population byte-for-byte, receipted by a
  checksum manifest.
- Brook-specific fixture overlays as declarative files on top of the generated base — the
  engineered patients the design docs name: mid-month program switch (the exclusivity-conflict
  regression), trinary verdict cases (`indeterminate` with mandatory reason), contradictory
  source states for genesis adjudication, quarantine-bound consent.
- `task synthea:regen` regenerates and verifies byte-identity via the manifest; staging
  regeneration is a scheduled/dispatch workflow calling that Taskfile target — `main.yml` stays
  exactly `task check` and Java/Synthea never runs inside `task check` (the cat4 CI-contract
  gate); unit tests cover overlay application and manifest verification only.

## Capabilities

### New Capabilities

- `synthetic-population`: deterministic, versioned synthetic patient population with declarative
  Brook fixture overlays — the single source for test, staging, and rehearsal data.

### Modified Capabilities

_None._

## Impact

- New workspace member (serial: workspace_roots); new Taskfile target; one new scheduled
  workflow that resolves to that target (cat4-compliant).
- Consumed by: `environment-matrix` (staging regen), `genesis-seed-run` rehearsal and its demo,
  object-model regression fixtures in downstream test suites.
- PHI: none, ever — the entire point. Synthea output is synthetic by construction; overlays are
  authored files.
- Rollback: delete the package and workflow; no consumer exists until environment-matrix lands.
