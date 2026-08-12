## Context

See proposal.md — Why. Constraints that shape the approach:

- **D4 (DNA-908, 2026-08-12): artifact, not live-apply.** The generator emits the serialized
  Metadata API operation set as a CI-built, validated artifact; a separate deploy step applies
  it; the same artifact promotes dev → staging → prod. Live-apply is rejected. The resolution
  carries a fallback clause — if the community scaffolding CLI cannot emit an artifact, the
  S0.2 Twenty-metadata generator emits its own — and this design takes the fallback as the
  primary implementation (Decision 1).
- **DNA-909 (open, manual): no Twenty dev instance exists.** Everything in this change must be
  buildable, testable, and mergeable against fixtures and golden files; anything needing a live
  server is isolated in one wave and named as gated.
- `design/platform/twenty-data-model.md` is the model of record (objects, fields, projection
  lookup, roles); `design/platform/pulse-app-scaffold.md` corrects its assumptions (base fields
  auto-added, `RAW_JSON` first-class, `isNullable`+default for NOT NULL, bidirectional
  relations, three-nullable-relations kept over MORPH).
- `pulse_core.catalog_gen` is the S0.2 pattern to inherit: pydantic-validated catalog load,
  deterministic rendering, golden-file tests, `catalog_generated_surfaces` serial lane.
- cat4 CI contract: `main.yml` run commands stay exactly `task check`; setup steps may install
  tools. `openspec`/`openlore` stay out of `task check`.
- Repo-wide test posture: no live network (`--disable-socket`), fixture-faked boundaries,
  synthetic data only.

## Goals / Non-Goals

**Goals:**

- One deterministic artifact expressing the whole Twenty workspace model, generated from
  `state_catalog.yaml` plus a checked-in model definition, validated in CI, applied only by a
  separate deploy step.
- `project-domain-event` as versioned, unit-tested TypeScript — the platform's only real
  projection logic, testable without a server.
- Stable identity: `universalIdentifier`s minted once into a checked-in map; a regeneration can
  never re-mint one (the app-scaffold doc's "or every sync recreates fields" hazard).

**Non-Goals:**

- No ledger-fed consumer — writing DomainEvent rows from ledger events is `twenty-projection`.
- No M1 retirement work (`m1-retire-patient-state`, gated on `twenty-projection`).
- No SPCS deployment plumbing (`pulse-spcs-deployment`, its own change; ADR-0004/D14).
- No staging/prod apply — this change proves dev apply only, and only once DNA-909 clears;
  promotion beyond dev rides `environment-matrix`.
- No live Twenty API pull or webhook work — D8's route already shipped in Phase 2.

## Decisions

1. **The generator is Python, in `pulse_core`, and the artifact contract is ours.** D4's primary
   phrasing points at the community CLI (`yarn twenty dev:build` manifest); its fallback clause
   licenses an own-generator artifact. We implement the fallback as primary because it is the
   only path provable today: the CLI's build is exercised end-to-end only against a running
   server (`app:publish` targets one), and no dev instance exists (DNA-909). The artifact
   contract — serialized Metadata API operation set, JSON, deterministic, schema-validated — is
   defined by this change's spec, not by either emitter. The CLI manifest path is evaluated in
   wave 3 (task 4.3) once a server exists; if `dev:build` proves artifact-capable and
   equivalent, a follow-on may swap the emitter behind the unchanged artifact contract.
   *Alternative considered:* wait for the instance and build CLI-first. Rejected — it serializes
   the whole phase behind a manual provisioning step for no spec benefit, and D4 explicitly
   permits the own-generator path.
2. **`universalIdentifier`s live in `packages/twenty-app/uid-map.json`, checked in, append-only.**
   Keyed by `<object>` / `<object>.<field>` / `<object>.<field>.<option>`. The generator reads
   the map; a key it needs but does not find is a **generation error instructing a mint**, never
   an auto-mint — an auto-minting generator is nondeterministic by construction and silently
   recreates fields on every sync. Minting is a reviewed diff (a task adds the map's initial
   population; later catalog states add entries the same way).
3. **Generate options arrays and the operation set — never whole TypeScript files.** Per the
   app-scaffold doc: hand-written object files import generated options
   (`generated/options.ts`, `generated/projection-lookup.ts` emitted by the same run that emits
   the artifact), so field definitions stay stable and reviewable. The Python artifact and the
   TS app source express one model because both consume the same generated options and the
   checked-in UID map; the artifact validator cross-checks the two (Decision 5).
4. **The deploy step is dumb by design.** `twenty_deploy` reads a validated artifact file and a
   target (`--target dev|staging|prod` resolving URL + credential from the environment, never
   code), replays the operation set idempotently (create-if-absent keyed on
   `universalIdentifier`, update-if-drifted, never delete), and emits a receipt of operation
   counts. Zero generation logic — promotion is the same file, next target, which is what makes
   "the same artifact promotes dev → staging → prod" true rather than aspirational.
   *Alternative considered:* deploy inside the generator behind a flag. Rejected — that is
   live-apply with extra steps, exactly what D4 closed against.
5. **Artifact validation runs in `task check`, Python-side.** Schema validation, byte-identical
   re-render (determinism), UID-map completeness (every generated surface key resolves), options
   ⊆ catalog states, and TS/artifact cross-check (the options the artifact carries equal the
   options `generated/options.ts` carries). Drift between catalog and committed artifact is a
   red check, the exact posture `catalog_gen`'s snapshot tests already set.
6. **Node enters CI as a setup step; run commands stay `task check`.** `task check` grows
   `twenty:test` (vitest unit suite, faked `CoreApiClient`) and the artifact checks;
   `main.yml` adds a pinned setup-node step. cat4 stays green because every `run:` still
   resolves to `task check`, and the new tools are step-installed — the same pattern go-task
   itself uses. The vitest suite runs no server and no network.
7. **Tests fake at two boundaries and nowhere else.** Python: the Metadata API HTTP boundary in
   `twenty_deploy` (a scripted transport; `--disable-socket` everywhere). TypeScript: the
   `CoreApiClient` the logic function handler receives. Live-server integration exists only in
   wave 3, marked and gated.

## Risks / Trade-offs

- **[Twenty Metadata API shape drift vs our serialization]** → the artifact schema is pinned in
  this repo and registered in `docs/contracts/consumes.md` against the Twenty version the image
  pin will carry; wave 3's read-back verification is the ground-truth check, and it runs before
  anything consumes the model. Until then the risk is bounded: nothing has applied the artifact
  anywhere.
- **[DNA-909 slips]** → waves 0–2 merge on fixtures alone; the change simply parks at execute
  with wave 3 undispatched, and `twenty-projection` stays gated behind this change as the
  roadmap already says. No task in waves 0–2 has a hidden instance dependency (enforced by
  `--disable-socket` in every test).
- **[First TypeScript package in a Python monorepo]** → contained: one package, vitest only,
  node pinned in CI as a setup step, no bundler, no publishing. If the toolchain fights the
  scaffold gates, the fallback is keeping `twenty:test` out of `check` behind an explicit
  cat4-visible target until resolved — recorded as a decision, not drifted into.
- **[UID map merge conflicts]** → append-only file edited by mint tasks under the
  `catalog_generated_surfaces` serial lane; never edited in parallel.
- **[CLI-manifest path turns out superior]** → cheap by construction: the artifact contract is
  emitter-independent (Decision 1), so a swap is a follow-on change touching the emitter and
  nothing downstream.

## Migration Plan

Pre-production, additive only. No instance exists at merge time for waves 0–2; wave 3's dev
apply is re-runnable (idempotent deploy) and its rollback is re-applying a prior artifact.
Reverting the change is removing `packages/twenty-app` and the two `pulse_core` modules; the
UID map is inert until first apply.
