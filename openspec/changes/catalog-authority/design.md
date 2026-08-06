# Design — catalog-authority

## Context

See proposal.md — Why. Constraints that shape the design:

- The generator exists and is load-bearing: `pulse_core.catalog_gen` reads
  `packages/pulse-core/src/pulse_core/catalog/state_catalog_seed.yaml` (`catalog_version:
  appendix-c-v0.7`) and emits the committed `pulse_core/generated/__init__.py`; a pytest in
  pulse-core asserts render-equals-committed, so drift is already gated in `task check`. The
  seed's own header carries the retirement clause: "once S0.2 catalog machinery is
  authoritative, `state_catalog.yaml` from the catalog release replaces this file and the
  generator's input path is the only thing that moves."
- D18 (ADR-0004, Accepted; runtime-readiness §4 verbatim): released versions live in Snowflake
  as versioned rows in a `catalog` schema (states, transitions, reason ValueSets, program
  config), tagged with an immutable `catalog_version`; edits stay in git; approval is the PR
  flow; merge to main triggers the release job; no hand edits in Snowflake, ever. Breaking = a
  release that removes a state, narrows a ValueSet, or changes a transition's legality;
  breaking requires a migration note and consumer checklist in the release PR.
- `task check` is the contract with CI, which holds no secrets — the release job cannot be a
  check step (`docs/contracts/consumes.md` posture; cat4 additionally requires every workflow
  `run:` step to resolve to a Taskfile target or a tool a step installs).
- `producer-ingress-policy` is gated on this change and needs a pinned artifact to check
  producer schemas against.
- No live network in tests; no PHI (the catalog carries no patient data and never will).

## Goals / Non-Goals

**Goals:**

- One authoritative file, one generator input, one release path — the generative contract of
  the object model §7 homed, not changed.
- Every enforcement that can run offline runs in `task check`: schema validity, generated-module
  drift, snapshot immutability, breaking-change classification, migration-note ceremony.
- The only credentialed surface is the deploy artifact (release entrypoint + workflow), with
  the plan/apply split `linear:sync` already models.

**Non-Goals:**

- No new generated surfaces: Twenty metadata, FSH/ConceptMaps, and dbt seeds remain their own
  changes (`pulse-app-scaffold`, `snowflake-projection`); this change wires the file and the
  release job, and the existing command-surface generator is the one regeneration target.
- No catalog content changes: v1.0.0 carries the seed's subjects and commands unchanged. The
  PX "non-response as first-class state" modeling question and any stage-rationalization edits
  are future catalog PRs through the machinery this change builds.
- No warehouse consumers wired here: dbt `accepted_values` binding reads the same tables when
  `snowflake-projection` lands.
- No Snowflake infrastructure provisioning (database, role grants, tag objects exist-or-created
  is the job's DDL, but granting the dedicated writer role and storing the workflow secret are
  deploy steps outside this change).

## Decisions

1. **The authoritative file lives at `catalog/state_catalog.yaml`, repo root.** It feeds four
   generated surfaces (object model §7), not just pulse-core, so it is a repo-level artifact,
   not a package resource. Regeneration is a dev/CI-time command reading a repo path; the
   committed generated module is what ships in the wheel, so packaging is unaffected.
   *Alternative rejected:* keeping it inside `pulse_core/catalog/` — couples the program-wide
   source of truth to one package and makes the `producer-ingress-policy` pin a
   package-internal path.
2. **Schema v1 = seed schema + `valuesets` + `programs`, semver `catalog_version`.** Subjects
   and commands carry over unchanged (the loader models extend `catalog_gen`'s existing
   Pydantic classes). `valuesets` holds the reason ValueSets (seeded with the referral closure
   reasons already ratified in the seed's comments: `deceased`, `duplicate`,
   `clinic_terminated`); `programs` holds the D11 set (PCM, CCM, RPM, APCM). Both new sections
   exist because D18's Snowflake rows and the breaking-change rule ("ValueSet narrowed")
   require them; the generator ignores them in v1.0.0 so the cutover stays behavior-identical.
   *Alternative rejected:* deferring valuesets/programs — leaves the breaking-change rule
   unenforceable on ValueSets and the `catalog` schema missing two of D18's four row kinds.
3. **Version convention: semver string, `1.0.0` first, MAJOR ⇔ breaking.** The breaking
   classifier decides what MAJOR means, so the convention is checkable, not aspirational.
   `appendix-c-v0.7` retires with the seed. This is the version convention
   `producer-ingress-policy` consumes.
4. **Cutover is verified by byte-diff.** The task that moves the generator input regenerates
   the module and asserts it differs from the previous committed module only in the version
   pin and source-provenance header — transition tables, command classes, and validators
   byte-identical. This is what makes a sonnet-tier cutover safe on the
   `catalog_generated_surfaces` serial lane.
5. **Immutability in git: snapshots + append-only checksum manifest.** Each release commits
   `catalog/releases/v<version>.yaml` (byte-identical copy) and a manifest entry
   (version → sha256). The offline gate checks head == current snapshot and every snapshot ==
   its manifest checksum. This is what lets the breaking-change check run in a fresh clone
   with no network: the previous version is always in the tree, so no `git diff` against a
   remote ref is needed (scaffold-gate rule: a gate must hold in a fresh clone).
   *Alternative rejected:* diffing against `origin/main` at check time — needs fetch depth and
   a remote, breaking the fresh-clone property.
6. **Breaking classification is a pure function over two loaded catalogs**, returning the list
   of breaking findings (removed states, narrowed ValueSets, legality changes — legality in
   either direction, verbatim §4.3; an added edge is a legality change and classifies
   breaking). The ceremony check composes it: classify the two newest manifest versions; if
   breaking, require MAJOR bump and `catalog/releases/v<version>-migration.md` containing the
   consumer checklist. Both run as pytest under `task check`.
7. **Release job = renderer + guard in `pulse_core.catalog_release`, executed via
   `task catalog:release`.** The renderer emits deterministic INSERT-only SQL (plus
   `CREATE ... IF NOT EXISTS` DDL for the `catalog` schema/tables/tags and
   `ALTER ... SET TAG` statements) — build ≠ publish, the same artifact posture D4 requires of
   the Twenty generator. The guard queries the version row first: absent → insert everything
   in one transaction; present with matching checksum → successful no-op (idempotent catch-up
   for versions released in git before the job was enabled); present with differing checksum →
   hard fail before any write. Execution goes through a thin connection boundary that tests
   fake — no live network, no snowflake driver import at test time.
   *Alternative rejected:* MERGE/upsert semantics — an upsert is exactly the "hand edit by
   job bug" D18 forbids; INSERT-only plus the guard makes rewriting released rows structurally
   unavailable.
8. **`task catalog:release` follows the `linear:sync` posture.** No credentials → print the
   rendered plan, exit 0; `APPLY=1` without credentials → error; `APPLY=1` with credentials →
   execute. The workflow `.github/workflows/catalog-release.yml` (push to main, `catalog/**`
   paths filter) runs `task catalog:release APPLY=1` with secrets from the repo environment —
   its `run:` steps are Taskfile targets, satisfying cat4. `task check` never depends on the
   target. Enabling secrets (and the GH Actions budget, currently $0 on this account) is a
   deploy step; until then the workflow is inert config, like the s13 schedule definitions.
9. **The dedicated writer role is the only writer.** The rendered DDL grants nothing; the
   runbook records that only the release job's role holds INSERT on the `catalog` schema and
   humans hold SELECT — access history plus object tagging answer "who read or changed catalog
   state" (runtime-readiness §4.2). Enforcing the grant is warehouse admin work outside this
   repo; the artifact records the posture.
10. **The successor's pin is stated once, in `docs/contracts/publishes.md`.**
    `producer-ingress-policy` consumes: `catalog/state_catalog.yaml` (authoritative file,
    repo head), the semver convention from decision 3, and `pulse_core.generated`
    (`CATALOG_VERSION`, `SUBJECT_TYPES`, `TRANSITIONS`, `COMMAND_TYPES`) as the programmatic
    surface. Nothing else this change builds is a contract for it.

## Risks / Trade-offs

- **[Byte-diff cutover masks a semantic change if the seed and authoritative file silently
  diverge during the change]** → the cutover task copies the seed's subjects/commands
  mechanically and the test compares generated output, not inputs; any divergence fails the
  diff. The serial lane guarantees no concurrent regeneration.
- **[Legality-change-in-either-direction makes most catalog edits breaking]** → accepted:
  verbatim §4.3, and honest — an added edge invalidates warehouse `Q_INVALID_TRANSITIONS`
  expectations and Twenty picklist behavior just as a removed one does. The ceremony cost is a
  migration note, which D18 prices in ("a breaking-change ceremony that every catalog edit now
  pays").
- **[Snapshot-per-version duplicates the catalog file]** → the catalog is small (KBs); the
  duplication buys offline, fresh-clone-safe history. The manifest keeps tampering detectable.
- **[The workflow cannot be proven end-to-end without credentials]** → the renderer, guard,
  and CLI posture are fully tested offline at the connection boundary; the workflow itself is
  validated by cat4 and a config-assertion test (trigger, paths filter, target), the same
  treatment s13 gave its schedule definitions. First credentialed run is a deploy-step
  verification with the runbook open.
- **[Checksum semantics: guard compares file checksum, renderer must hash the same bytes the
  snapshot froze]** → one checksum definition (sha256 of the snapshot file) used by manifest,
  version row, and guard; a test pins that all three agree.
- **[GH Actions budget $0 could silently skip the merge-to-main trigger]** → known account
  posture (docs/ci-lessons territory); the runbook's release procedure includes running
  `task catalog:release APPLY=1` manually as the fallback, which is identical to what the
  workflow runs.

## Migration Plan

Additive and pre-production. Order inside the change: authoritative file + loader → generator
cutover (serial lane, seed deleted in the same task so no window with two sources) → snapshots
and classification gates → release renderer/guard/CLI → workflow + docs. Rollback before any
credentialed run is `git revert` (restores the seed and the old input path; the generated
module regenerates back). After a credentialed run, rollback still never touches released
Snowflake rows — they are immutable by design; a bad release is corrected by the next version,
never by editing rows.

## Open Questions

- Snowflake database name that homes the `catalog` schema (account-level naming, e.g. which
  database staging vs prod maps to). The renderer takes it as configuration with a placeholder
  default; the first credentialed deploy pins it. Does not change specs, approach, or tasks.
