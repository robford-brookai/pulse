# Tasks — catalog-authority

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket`): the Snowflake side is exercised against rendered SQL and a faked
connection boundary; every offline gate must hold in a fresh clone. No PHI anywhere — the catalog
is states, transitions, ValueSets, and program config only.

---

## 1. Wave 0 — schema and authoritative file

- [x] 1.1 [DNA-863] Authoritative catalog schema and file: extend the `pulse_core.catalog_gen` loader models
      with `valuesets` and `programs` sections and a semver `catalog_version`; write
      `catalog/state_catalog.yaml` at `1.0.0` — subjects and commands carried over from the
      Appendix C seed unchanged, referral closure reasons (`deceased`, `duplicate`,
      `clinic_terminated`) as the seeded ValueSet, D11 programs (PCM, CCM, RPM, APCM). Validation
      rejects unknown keys, transitions to undeclared states, non-semver versions. Tests: the
      authoritative file loads into the validated model (spec: "A schema-valid catalog loads");
      each malformed variant fails naming the offending entry with no partial catalog (spec: "A
      malformed catalog is rejected naming the violation").
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      Model `opus`: the catalog schema is the contract every generated surface and the release
      job derive from — a defect here is retrofit-expensive across all of them.

## 2. Wave 1 — generator cutover and snapshots

- [x] 2.1 [DNA-864] Generator input cutover: `pulse_core.catalog_gen` reads `catalog/state_catalog.yaml`
      (repo root) as its only input; delete the seed file and every reference to it; regenerate
      `pulse_core/generated/__init__.py` pinned to `1.0.0`. Tests: the regenerated module differs
      from the previous committed module only in the version pin and source-provenance header —
      transition tables, command classes, validators byte-identical (spec: "The generated module
      derives from the authoritative catalog"); the seed file is absent and unreferenced (spec:
      "The Appendix C seed is retired"). The existing render-equals-committed drift test keeps
      gating regeneration in `task check`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
      `serial: catalog_generated_surfaces` — regenerates the one generated contract producers and
      the validator both derive from; releases alone (the pulse-ledger-core 2.1 lane).
- [x] 2.2 [DNA-865] Release snapshots and the immutability gate: freeze `catalog/releases/v1.0.0.yaml`
      (byte-identical copy) and the append-only checksum manifest; a pytest under `task check`
      verifies head == current-version snapshot and every snapshot == its manifest checksum, all
      offline in a fresh clone. Tests: a consistent tree passes (spec: "The head catalog matches
      its release snapshot"); a snapshot that no longer matches its checksum, or a head that
      diverges from its version's snapshot, fails naming the rewritten version (spec: "A tampered
      snapshot fails the gate").
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 3. Wave 2 — the breaking-change rule

- [x] 3.1 [DNA-866] Breaking classifier: a pure function over two loaded catalogs returning the breaking
      findings — removed states, narrowed ValueSets, transition legality changes in either
      direction (runtime-readiness §4.3 verbatim); additive-only diffs classify non-breaking.
      Tests: dropped state names the state (spec: "A removed state classifies breaking"); removed
      ValueSet code names set and code (spec: "A narrowed ValueSet classifies breaking"); a
      removed and an added edge each name the edge (spec: "A transition legality change
      classifies breaking"); new states/codes/programs only → non-breaking (spec: "An additive
      release classifies non-breaking").
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 2]`
      Model `opus`: this function *is* the D18 breaking-change rule — misclassification ships
      silent breaking releases to every consumer.
- [x] 3.2 [DNA-867] Ceremony enforcement in `task check`: classify the two newest manifest versions; a
      breaking diff requires the MAJOR bump and `catalog/releases/v<version>-migration.md`
      carrying the consumer checklist (Twenty metadata redeploy, ConceptMap regeneration,
      rule_version bump if verdict criteria reference the changed codes). Tests: breaking diff
      with missing note or un-bumped major fails naming the missing artifact (spec: "A breaking
      release without a migration note fails the check"); breaking diff with bump + note passes
      (spec: "A conformant breaking release passes").
      `[model: sonnet | deps: 3.1, 2.2 | lane: repo_change | wave: 2]`

## 4. Wave 2/3 — the Snowflake release job

- [x] 4.1 [DNA-868] Release renderer (`pulse_core.catalog_release`): deterministic output for one catalog
      version — `CREATE ... IF NOT EXISTS` DDL for the `catalog` schema, tables, and tag;
      INSERT-only rows for states, transitions, ValueSets, programs, and the version row
      (version, git identity, sha256 of the snapshot file, breaking classification); `SET TAG`
      statements. Database name is configuration with a placeholder default (design open
      question). Tests: rendered output covers all five row kinds, every row stamped with the
      version, no UPDATE/DELETE anywhere, byte-identical across runs (spec: "A release renders
      insert-only rows for every catalog surface"); tag statements mark the catalog objects with
      the released version (spec: "Catalog objects are tagged with the release version").
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 2]`
      Model `opus`: the rendered rows are the warehouse contract dbt tests and every catalog
      consumer read from — the release-job contract D18 names.
- [x] 4.2 [DNA-869] Immutability guard and plan/apply execution: query the version row through a thin
      connection boundary (faked in tests, no snowflake driver import at test time); absent →
      single-transaction apply; present with matching checksum → successful no-op; present with
      differing checksum → hard fail before any write. One checksum definition shared by
      manifest, version row, and guard, pinned by a test. Tests: identical re-release writes
      nothing and reports already-released (spec: "An identical re-release is a no-op");
      conflicting re-release fails before any insert, naming version and both checksums (spec:
      "A conflicting re-release fails before any write").
      `[model: sonnet | deps: 4.1 | lane: repo_change | wave: 3]`
      Depends on 4.1, not parallel: both edit `catalog_release.py`, so they serialize to avoid a
      same-wave merge conflict.
- [x] 4.3 [DNA-870] `task catalog:release` and the deploy artifact: Taskfile target with the `linear:sync`
      posture (no credentials → print plan, exit 0; `APPLY=1` without credentials → error;
      `APPLY=1` with credentials → execute); `.github/workflows/catalog-release.yml` on push to
      main with a `catalog/**` paths filter, `run:` steps resolving to Taskfile targets (cat4);
      never referenced by `task check`. Config only — secrets and the Actions budget are deploy
      steps outside this change. Tests: credential-free plan run prints the rendered plan and
      exits zero with no network (spec: "Planning without credentials"); `APPLY=1` without
      credentials exits nonzero naming the missing credentials (spec: "Apply without credentials
      is an error"); an assertion that `check`'s dependency closure excludes the release target
      and a config test on the workflow trigger/paths/target (spec: "The check contract stays
      credential-free").
      `[model: sonnet | deps: 4.2 | lane: repo_change | wave: 3]`
      `serial: workspace_roots` — edits `Taskfile.yml` and `.github/workflows/`.

## 5. Wave 4 — docs and the successor's pin

- [x] 5.1 [DNA-871] Docs: `docs/contracts/publishes.md` gains the catalog as a published surface — the
      `producer-ingress-policy` pin stated once: `catalog/state_catalog.yaml` at repo head,
      semver `catalog_version` (MAJOR ⇔ breaking), programmatic surface `pulse_core.generated`
      (`CATALOG_VERSION`, `SUBJECT_TYPES`, `TRANSITIONS`, `COMMAND_TYPES`), plus the Snowflake
      `catalog` schema as the warehouse read surface. Update the
      `design/platform/state-catalog.md` supersession note (the "until `catalog-authority`
      lands" clause resolves) and the seed-retirement wording; write
      `docs/runbooks/catalog-release.md` — release procedure, the manual
      `task catalog:release APPLY=1` fallback for the $0-budget account posture, the
      no-hand-edits rule and writer-role posture, conflicting-checksum triage. mkdocs nav
      entries; placeholders as inline code, never link syntax. Gate: `mkdocs build -s` green.
      Test: a consumer-contract check reads `catalog/state_catalog.yaml` and imports
      `pulse_core.generated`, asserting both agree on `catalog_version` and the state/command
      vocabulary with no other surface consulted (spec: "A consumer resolves the contract
      surfaces").
      `[model: sonnet | deps: 2.1, 3.2, 4.3 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater lane, spec-adjacent files.
