# Tasks — pulse-app-scaffold

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

**DNA-909 gate boundary.** Waves 0–2 are pure codegen/artifact/fixture work and dispatch now —
no task in them touches a live Twenty instance, enforced by `--disable-socket` in every Python
test and a faked `CoreApiClient` in every vitest test. **Wave 3 requires the Twenty dev
instance (DNA-909, manual provisioning, open) and must not dispatch until Rob closes it.** A
Blocked sub-issue on either wave-3 task parks the change at execute per WORKFLOW.md; that is
the expected state if DNA-909 is still open when wave 2 merges.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). Synthetic data
only — the generator input is the state catalog (vocabulary, never patient data); any
patient-shaped fixture value draws on `packages/synthea-seed` shapes. No PHI in fixtures,
golden files, logs, or receipts.

---

## 1. Wave 0 — scaffold

- [x] 1.1 Scaffold `packages/twenty-app` as a workspace member: package layout per
      `design/platform/pulse-app-scaffold.md` (src/objects, src/roles, src/logic-functions,
      src/views, generated/, tests/), `package.json` with vitest + typescript pinned,
      `uid-map.json` created empty-but-valid, and Taskfile targets `twenty:gen`,
      `twenty:test`, `twenty:deploy` defined (gen/test wired to real commands, deploy to the
      CLI task 3.3 ships) — none added to `task check` yet (that is 3.4's reviewed step).
      Test: a placeholder vitest spec collects and passes via `task twenty:test`; `task check`
      stays green and unchanged.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits `Taskfile.yml` and repo root config. Declared scope
      must equal executed scope (the pulse-ledger-core 1.1 lesson).

## 2. Wave 1 — generator and artifact

- [x] 2.1 Model definition and initial UID mint: encode the
      `design/platform/twenty-data-model.md` objects (Patient, Program, PatientProgram,
      Provider, Clinic, DomainEvent) as checked-in model-definition data in
      `pulse_core/twenty_model.py` — fields, types, relations (three nullable relations, no
      MORPH), required/default flags per the app-scaffold corrections (no base fields,
      `RAW_JSON` first-class, `isNullable: false` + default for NOT NULL) — and populate
      `packages/twenty-app/uid-map.json` with minted `universalIdentifier`s for every object,
      field, and current-catalog option, keyed `<object>` / `<object>.<field>` /
      `<object>.<field>.<option>`.
      Tests: model definition validates (every relation names a defined object, every SELECT
      field maps to a catalog dimension); the UID map covers exactly the model + catalog
      surface (no missing, no orphan keys); all UUIDs well-formed and unique.
      `[model: fable | deps: 1.1 | lane: repo_change | wave: 1]`
      `serial: catalog_generated_surfaces` — this file pair is the generation input every
      later regeneration reads; parallel edits would fork the model.
      Fable: this is where the model's spec quality gets set — a wrong field type, relation
      direction, or UID key scheme propagates into every generated surface and is
      retrofit-expensive after first apply (UIDs are mint-once by spec).

- [ ] 2.2 Generator `pulse_core/twenty_metadata.py`: read `state_catalog.yaml` through
      `catalog_gen.load_catalog`, read the model definition and UID map, emit
      `packages/twenty-app/generated/options.ts`, `generated/projection-lookup.ts`, and the
      serialized Metadata API operation set artifact
      (`packages/twenty-app/artifact/operations.json`) — objects, fields, relations, picklist
      options, and the single-writer role set (producers create-only DomainEvent; staff
      read-only status fields and DomainEvent; app role minimal). Deterministic rendering
      (sorted iteration, `catalog_gen`'s posture); a UID-map miss is a generation error naming
      the key, never a mint.
      Tests: golden files for all three outputs; byte-identical double-render; a catalog state
      appears in options, artifact picklist, and lookup from one run (spec: "A catalog state
      becomes a SELECT option everywhere at once"); UID miss errors by key with map unchanged
      (spec: "A missing UID is a generation error"); staff role grants read-not-write on every
      status field (spec: "Staff cannot write a status field"); runs under `--disable-socket`
      (spec: "Generation is offline").
      `[model: opus | deps: 2.1 | lane: repo_change | wave: 1]`
      `serial: catalog_generated_surfaces` — emits the generated surfaces; standing serial-lane
      member per dispatch-template §4.
      Opus: judgment inside one package — the operation-set serialization must express the
      model without inventing shape, and the golden files it mints become the verifier every
      later task trusts.

- [ ] 2.3 Artifact validation in `task check`: `pulse_core/twenty_validate.py` — operation-set
      schema validation, committed-artifact-matches-regeneration (staleness check), UID-map
      completeness, options ⊆ catalog states, and TS/artifact option-set equality — exposed as
      `task twenty:validate` and added to `task check`'s dependency list (Python-side only; no
      node needed to validate JSON against TS via parsing the generated options file as data).
      Tests: each validator rejects a minimally-broken fixture (drifted artifact, missing UID,
      option not in catalog, TS/artifact mismatch) and passes the committed tree (spec: "A
      drifted committed artifact fails CI"; "Re-render is byte-identical").
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 1]`
      `serial: workspace_roots` — edits `Taskfile.yml`'s `check` target; per docs/ci-lessons.md,
      read it before touching `check`, and cat4 must stay green.

## 3. Wave 2 — app source, deploy step, wiring

- [ ] 3.1 TypeScript app model in `packages/twenty-app/src/`: `application-config.ts`, one
      object file per model object importing its options from `generated/options.ts` and its
      `universalIdentifier`s from the UID map, role definitions, and the ops-facing saved
      views — hand-written files consuming generated arrays, never generated whole (design
      Decision 3).
      Tests (vitest): every object file's UIDs resolve in the map; every SELECT field's options
      import from generated code (no literal option arrays in hand-written files); model
      typechecks under `tsc --noEmit` via `task twenty:test`.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2]`

- [ ] 3.2 `src/logic-functions/project-domain-event.ts`: the handler behind an injected
      client boundary — crosswalk resolution, first-event PatientProgram creation,
      per-dimension LWW guard, lookup apply from `generated/projection-lookup.ts`,
      unresolved-ref orphan stop, lookup-miss no-op.
      Tests (vitest, faked client): the five app-scaffold cases — late event no-op with event
      logged (spec: "A late event is a no-op on state"), unresolved ref stops cleanly (spec:
      "An unresolvable ref stops cleanly"), dimension isolation (spec: "Dimensions are
      isolated"), first event creates the pair row (spec: "First event for a pair creates the
      PatientProgram row"), lookup miss no-op (spec: "A lookup miss is a no-op").
      `[model: opus | deps: 3.1 | lane: repo_change | wave: 2]`
      Opus: the projection apply semantics are the platform's only real logic in Twenty; an LWW
      or dimension-isolation mistake silently corrupts projected state and only surfaces at
      reconciliation.

- [ ] 3.3 Deploy CLI `pulse_core/twenty_deploy.py` + `task twenty:deploy`: artifact file +
      `--target` (URL/credential from environment, never code), validate-before-apply
      (refuses on any 2.3 validator failure), idempotent apply keyed on `universalIdentifier`
      (create-if-absent, update-if-drifted, never delete), `--dry-run` plan with fixture
      transport and no sockets, receipt with names/counts/artifact checksum only — error paths
      never echo response bodies.
      Fixtures: scripted transports for empty target, matching target, drifted target, one
      failing operation with a synthetic record value in the body.
      Tests: invalid artifact refused before any operation (spec: "An invalid artifact is
      refused"); re-apply is all no-ops and no delete ever attempted (spec: "Re-apply of the
      same artifact is all no-ops"); same artifact to two targets yields equal checksums in
      receipts (spec: "Two targets, one artifact, matching checksums"); dry-run sends nothing
      under `--disable-socket` (spec: "Dry-run sends nothing"); failure receipt carries no
      response-body value (spec: "A failed operation's receipt is safe to attach").
      `[model: sonnet | deps: 2.3 | lane: repo_change | wave: 2]`

- [ ] 3.4 CI wiring: add `twenty:test` (vitest + tsc) to `task check`, add a pinned
      setup-node step to `.github/workflows/main.yml` — every `run:` command stays exactly
      `task check` (cat4 contract; read `docs/ci-lessons.md` first). `openspec`/`openlore`
      stay out of `check`, unchanged.
      Tests: `tests/scaffold/cat4_ci_contract.py` green; `task check` green in a fresh clone
      posture (node present) — and the scaffold gates still collect.
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 2]`
      `serial: workspace_roots` — edits CI workflow and `Taskfile.yml` `check`; the exact
      surface cat4 and ci-lessons exist for, never edited in parallel.

- [ ] 3.5 Register the consumed surface: `docs/contracts/consumes.md` entry for the Twenty
      Metadata API — operation-set shape the artifact serializes against, pinned to the Twenty
      version the image pin will carry (per `pulse-app-scaffold.md` §SPCS: pinned upstream
      tag), cross-linking DNA-908 (D4) as the deciding record and DNA-909 as the instance
      dependency.
      Test: `mkdocs build -s` green; a doc-presence test asserts the entry names the artifact
      path and the pinned version key.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 2]`
      `serial: openspec_main_specs` — doc-updater lane: `docs/contracts/consumes.md` is a
      single shared file every consumer-registering change edits; this task owns the edit for
      this change.

## 4. Wave 3 — live dev verification (GATED: DNA-909)

**Do not dispatch this wave until DNA-909 (Twenty dev instance, manual) is Done.** Both tasks
run against the dev instance with synthetic data only; neither touches staging or prod
(promotion beyond dev is `environment-matrix`).

- [ ] 4.1 Apply the artifact to the dev instance and verify by read-back: `task twenty:deploy`
      `--target dev` with the committed artifact, then schema read-back through the Metadata
      API asserting every artifact operation's target present with its mapped
      `universalIdentifier` (spec: "Read-back matches the artifact"); re-apply immediately and
      assert an all-no-op receipt against the live target. Verification receipt (names,
      counts, checksum — no workspace data) attached to this change's Linear parent.
      Test: a repo-committed verification script exits nonzero on any read-back mismatch; its
      output is the receipt.
      `[model: sonnet | deps: 3.3, 3.4 | lane: repo_change | wave: 3]`
      Gate: DNA-909. First live contact — runs alone before 4.2 so a metadata defect is
      isolated from function behavior.

- [ ] 4.2 Live logic-function verification and the promotion runbook: install the app surface
      on dev per the scaffold doc's dev loop, exercise `project-domain-event` for the five
      3.2 cases against the live server (`dev:function:exec` or synthetic DomainEvent
      creates), record the create-twenty-app manifest evaluation (design Decision 1: can
      `dev:build` emit an equivalent artifact offline? — findings to HANDOFF.md for the
      doc-updater, never applied as drift), and write `docs/runbooks/twenty-artifact-promotion.md`
      (same artifact, next target; rollback = re-apply prior artifact).
      Tests: the five live cases scripted with nonzero exit on any failed assertion (receipt
      to the Linear parent); `mkdocs build -s` green with the runbook linked.
      `[model: opus | deps: 4.1 | lane: repo_change | wave: 3]`
      Gate: DNA-909. Opus: live-behavior adjudication plus the CLI-manifest evaluation —
      judgment about equivalence that the escalation ladder should not discover at sonnet.
