# Design — synthea-seed

## Context

See proposal.md — Why. Constraints: the cat4 CI-contract gate requires `main.yml` to run exactly
`task check` and every workflow `run:` to resolve to a Taskfile target; `task check` must pass
on CI runners with no Java. Runtime readiness §2 fixes the tier shapes (dev ~500 patients,
staging ~50k prod-shaped) and the rule that PHI never leaves prod — there is no sanitized-copy
tier, which is exactly why this package exists.

## Goals / Non-Goals

**Goals:** determinism as a receipt (manifest), fixtures as data (overlays), regeneration as
infrastructure (Taskfile + scheduled workflow), one source for all test populations.

**Non-Goals:** de-identification pipelines (explicitly rejected by §2.1); loading data anywhere
(environment-matrix owns that); FHIR profile work beyond what Synthea emits.

## Decisions

1. **Package `packages/synthea-seed`**, module `synthea_seed`. Synthea runs via its released
   JAR, version-pinned by checksum in the package config; the wrapper shells out — no JVM
   bindings. Java is a documented prerequisite of `task synthea:regen` only.
2. **Two population profiles** in one config: `dev` (~500) and `staging` (~50k), same seed
   discipline, separate manifests. Dev output small enough to regenerate locally in minutes.
3. **Overlay format: YAML per fixture**, schema-validated (Pydantic), applied by patient
   identifier against the generated base; each overlay names the design-doc fixture it
   implements (mid-month switch → object-model exclusivity regression; contradiction set →
   genesis §2 conflict classes; quarantine consent → Gate B posture).
4. **Manifest = sha256 per output file + a top hash**, committed. Re-pin is an explicit,
   reviewed change to the manifest, never automatic.
5. **Workflow**: `synthea-regen.yml` on `workflow_dispatch` + schedule, running
   `task synthea:regen PROFILE=staging`; artifact upload for the staging loader
   (environment-matrix consumes it later). Keeps cat4 green by construction.

## Risks / Trade-offs

- **Synthea's own determinism across platforms** (JVM/locale differences) → the manifest is
  authored from the CI runner's output, and local divergence is diagnosed by the manifest diff;
  if cross-platform nondeterminism appears, the receipt narrows to the CI artifact and the
  README says so.
- **50k staging generation time in CI** → scheduled, not per-PR; dev profile covers the
  inner loop.
