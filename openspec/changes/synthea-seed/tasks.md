# Tasks — synthea-seed

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. Linear ids
get bracketed in after `task linear:sync`. Tests ship in the same commit; no generation and no
Java in any test — unit tests cover overlay application and manifest verification only.

---

## 1. Wave 0 — scaffold and pins

- [x] 1.1 Scaffold `packages/synthea-seed` as a workspace member; pin Synthea JAR version (by
      checksum), module config, RNG seed, and the two population profiles (dev ~500, staging
      ~50k); define the checksum-manifest format. Tests: manifest format round-trips; pin
      config validates.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits the root workspace manifest.

## 2. Wave 1 — generation and fixtures

- [x] 2.1 Generation wrapper + `task synthea:regen PROFILE=<p>`: shell out to the pinned JAR,
      verify output against the profile's manifest, exit nonzero naming diverging files;
      manifest re-pin is explicit. Tests: verification logic against fixture trees (no
      generation run).
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
- [ ] 2.2 Brook overlay fixtures + application logic: YAML per fixture, schema-validated,
      deterministic application; ship the four named fixture sets (mid-month exclusivity
      switch, trinary verdicts incl. indeterminate-with-reason, genesis contradiction set,
      quarantine-bound consent). Tests: deterministic double-apply; malformed overlay rejected
      naming file and reason; each named fixture present in the applied result.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      Model `opus`: the fixtures encode object-model semantics — a wrong fixture silently
      weakens every downstream regression suite.

## 3. Wave 2 — CI wiring

- [ ] 3.1 `synthea-regen.yml` workflow (`workflow_dispatch` + schedule) calling
      `task synthea:regen PROFILE=staging` and uploading the artifact; cat4 gate green
      (`main.yml` untouched, every `run:` resolves to a Taskfile target); README documents the
      Java prerequisite as regen-only. Tests: scaffold cat4 check passes; smoke-parse of the
      workflow.
      `[model: sonnet | deps: 2.1, 2.2 | lane: repo_change | wave: 2]`
