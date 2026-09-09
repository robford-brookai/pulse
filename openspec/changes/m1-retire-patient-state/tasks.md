# Tasks — m1-retire-patient-state

Annotation format, read by `task dispatch`:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps`
names task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). `task check` stays
green, offline and credential-free at every step: fixtures and the offline Postgres stand-in only,
no live bus, ledger or Hasura in tests. Synthetic data only; no PHI, no real patient identifiers in
fixtures, logs, receipts, or golden files. Specs are owned by the doc-updater: write proposed spec
changes to `HANDOFF.md`, never edit `openspec/specs/`.

**Entry conditions.** Second change in flight alongside `reconciliation-sweeps`, whose only open
task is the attended 4.1; the two share `packages/schedules/src/schedules/sweep_registry.py`
consumers only through task 3.1 here, which releases after that change's code is on main (it is).
Alembic migrations under `packages/ocean/infra/postgres/versions/` are a serial lane. Task 4.1 is
live execution (GitHub issue + runbook PR + attended run per WORKFLOW v2.2.0 `live_execution`),
never a worktree.

---

## 1. Wave 0 — the projection replaces the bootstrap

- [x] 1.1 Patient-state projection handler: `packages/ocean/services/graph-projection/src/handlers/patient_state.py`
      subscribes to `patient-state` events for `enrollment` subjects, resolves the canonical
      patient id (the lookup `twenty-projection` uses), mints or updates `patients`
      (`enrollment_status` = resulting catalog state, `ledger_seq` = event sequence) monotonically
      on `ledger_seq`, parks unresolvable subjects, and exposes `rebuild(journal_reader)` (spec:
      "A row is minted by the first enrollment event", "Apply is monotonic", "Legacy rows are
      marked"; design.md decisions 1, 2, 5).
      Tests: first event mints; older event is a counted no-op; redelivery unchanged; legacy row
      adopted on first event; unresolvable subject parks and the consumer continues; a PHI tripwire
      asserts no payload field beyond the state name reaches a log or receipt.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      Opus because the handler decides which ledger events create patients; a wrong rule mints
      the wrong subjects for every clinic.

- [x] 1.2 Schema: an Alembic migration under `packages/ocean/infra/postgres/versions/` that drops
      `enrollment_status`'s server default, adds `ledger_seq BIGINT NULL`, and drops and recreates
      `patient_graph_summary` with `ledger_seq` in the select and group-by plus its unique index;
      `models.py` loses `default="pending"` and gains `ledger_seq` (design.md decisions 3, 7).
      Tests: migration upgrade and downgrade round-trip on the offline Postgres stand-in; legacy
      rows keep their status and read `ledger_seq IS NULL`; the view exposes the new column.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0 | serial: Alembic versions directory, one head]`

- [x] 1.3 Delete the bootstrap insert (`alerts.py` STEP 1) and the normalizer's asserted status
      (`impilo-connector/src/normalizer.py` `patient.*` payload) (spec: "Only the ledger projection
      mints", "No asserted enrollment state travels the bus"; design.md decisions 6, 8).
      Tests: an alert for an unknown patient lands with no `patients` row created; the normalizer's
      `patient.*` payload has no `enrollment_status` key; existing alert and normalizer suites stay
      green (fixtures that inserted `patients` rows are updated to go through the projection
      fixture instead).
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 0]`

- [x] 1.4 Route the feed: add `patient-state` to `CONSUMER_DOMAINS["graph-projection"]` in
      `packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py` and regenerate
      `packages/ocean/infra/terraform/generated/event_catalog.auto.tfvars.json` with
      `packages/ocean/scripts/generate_event_catalog.py`, so graph-projection's EventBridge rule
      matches the ledger relay's `("ocean", "patient-state")` address (design.md decision 11).
      Tests: `consumer_rule_pattern("graph-projection")` matches source `ocean`, detail-type
      `patient-state`; the committed tfvars carries that pattern; every other consumer's pattern is
      byte-for-byte unchanged; the ocean-broker and SYNC_04 suites stay green.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0 | serial: generated terraform surface, one regen]`

## 2. Wave 1 — read-only, and the surfaces cut over

- [ ] 2.1 Read-only enforcement: `packages/ocean/tests/gates/test_patients_read_only.py` fails on
      any `INSERT INTO patients` or `UPDATE patients` outside `handlers/patient_state.py`;
      `infra/hasura/apply_metadata.py` grants select-only on `patients` for every service role
      (design.md decision 4).
      Tests: the gate passes on the tree and fails on a planted stray insert in a temp copy; the
      metadata builder emits select-only permissions for `patients` and unchanged relationships.
      `[model: sonnet | deps: 1.2, 1.3 | lane: repo_change | wave: 1]`

- [x] 2.2 Read surfaces: stacte-bridge `crud_api.py` descriptions say `enrollment_status` is
      projected from the ledger, read-only, cited by `ledger_seq`; slack-bot's Hasura query selects
      `ledger_seq` and the `*Status:*` line renders the catalog state, marking a null citation as
      legacy and unverified (spec: "The read surfaces present the projected state and its
      citation").
      Tests: crud_api schema golden; slack render for a projected row and a legacy row.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 1]`

## 3. Wave 2 — the sweep and the record

- [x] 3.1 Registry: `packages/schedules/src/schedules/sweep_registry.py` (or its consumer
      registration module) moves `graph-projection-patients` to `cite_field="ledger_seq"`, family
      `enrollment`, `owning_change=None`, with a `PatientsReader` that returns
      `(patient_id, enrollment_status, ledger_seq)` rows (spec: "The projection is a citable
      consumer"; design.md decision 9).
      Tests: registry × consumer matrix golden updated; a projected row agrees, a legacy row counts
      as uncitable, a missing citation is `uncitable` not `state`.
      `[model: sonnet | deps: 1.1, 1.2 | lane: repo_change | wave: 2]`

- [ ] 3.2 Docs via `HANDOFF.md`: ADR §6.2 retirement note (dated, naming the four clauses and the
      PRs), roadmap Phase 3 row and v3.0 exit table (M1 clause met), `publishes.md` row for the
      projection as a `patient-state` consumer, runbook `docs/runbooks/m1-patients-projection.md`
      (attended migration, `terraform apply` of the `eventbridge-ocean` consumer rule, rebuild,
      Hasura apply, first sweep), mkdocs nav.
      Tests: `mkdocs build -s`; cat8 docs gates; `task check` green.
      `[model: haiku | deps: 1.4, 2.1, 2.2 | lane: repo_change | wave: 2]`

## 4. Wave 3 — attended run

- [ ] 4.1 Live execution on dev: GitHub tracking issue; apply the migration on dev's graph
      Postgres; `terraform apply` the `eventbridge-ocean` module so graph-projection's rule includes
      `patient-state`, and confirm the rule pattern from the CLI; run `patient_state.rebuild` over the journal for `enrollment` subjects; apply Hasura
      metadata; run the `enrollment` conformance sweep once and post its receipt (counts and subject
      keys only): projected rows agree, legacy rows counted as uncitable, no `patients` write from
      any other path during the run.
      Tests (runbook assertions): the consumer rule pattern lists `patient-state`; zero
      `INSERT INTO patients` from graph-projection logs outside the handler; view returns `ledger_seq` for projected rows; sweep receipt shows the consumer as
      citable.
      `[model: sonnet | deps: 1.4, 3.1, 3.2 | lane: operational_discovery | wave: 3]`
